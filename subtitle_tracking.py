"""Bounded active subtitle tracking; no global fuzzy translation memory."""
from dataclasses import dataclass
import re
import uuid
import math

from core import clean_ocr

SPEAKER = re.compile(r"(?<![\w])((?:(?:Mr|Mrs|Ms|Dr|Prof|Capt|Sgt)\.\s+)?(?:[A-Z][a-zA-Z'-]*(?:[ -][A-Z][a-zA-Z'-]*){0,2}|[A-Z]{2,6})):\s*")
FUNCTIONS = set("i ill ive i'll i've we you he she it they then this that the a an and but or if so maybe no yes hey what how where when why even good like makes have do get let go its follow stay wait take run stop close keep look please tell".split())


@dataclass
class Candidate:
    text: str
    speaker: str
    body: str
    confidence: float
    box: tuple | None = None
    indices: tuple = ()


def split_speaker(text):
    match=SPEAKER.match(text)
    if match:
        return match[1],text[match.end():]
    return '',text


def comparison_glyphs(text):
    text=text.replace('’',"'").replace('“','"').replace('”','"')
    # These repairs are comparison keys only; never rewrite the stored observation.
    text=re.sub(r"(?<!\w)(?:[Ii]\s*'?\s*l(?:\s*l)?|l\s*'\s*ll)\b(?=\s+(?:let|be|get|go|do|see|find|tell|call|take|make|have|come|try|give)\b)",'ill',text)
    text=re.sub(r"(?<!\w)(?:[Iil]\s*'?\s*ve|'ve)\b",'ive',text)
    return text


def normalized(text):
    text=comparison_glyphs(text)
    text=re.sub(r'(?<=[a-zA-Z])0(?=[a-zA-Z])','o',text)
    return re.sub(r'[\s.,;:"!…-]+','',text.casefold())


def protections(text):
    text=re.sub(r'\b(?:[A-Z]{1,3}\.){2,}[A-Z]{0,3}\.?',lambda m:m[0].replace('.',''),text)
    folded=text.casefold().replace('’',"'")
    words=re.findall(r"[a-z]+(?:'[a-z]+)?",folded)
    negative=[w.replace("'",'') for w in words if w in ('no','not','never','without','neither','nor','cannot')
              or w.endswith("n't") or w in ('cant','dont','wont','isnt','arent','wasnt','werent','didnt','doesnt','shouldnt','wouldnt','couldnt','hasnt','havent')]
    numbers=re.findall(r'(?<![\w])\d+(?:[.,]\d+)*(?![\w])',text)
    names=[]
    for word in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?",text):
        if word[0].isupper() and normalized(word) not in FUNCTIONS and len(word)>1:
            names.append(word.replace('’',"'"))
    return sorted(negative),numbers,names,('?' in text),('!' in text)


def equivalent(a,b):
    if clean_ocr(a)==clean_ocr(b): return True
    # Protect semantics after the same narrowly scoped glyph repairs as the key.
    # Preserve all remaining proper nouns, quantities, negations and questions.
    def signature(text):
        text=comparison_glyphs(text)
        p=protections(text)
        return p[:4]  # Question vs statement stays protected; emphasis may flicker.
    if signature(a)!=signature(b): return False
    if normalized(a)!=normalized(b): return False
    # A space can carry meaning. Do not treat these boundaries as OCR noise.
    for joined,apart in (('nowhere','now here'),('apart','a part'),('already','all ready'),
                         ('along','a long'),('alone','a lone'),('anymore','any more')):
        if (joined in a.casefold() and apart in b.casefold()) or (joined in b.casefold() and apart in a.casefold()):
            return False
    # Long lines provide enough context to tolerate a missing space/contraction.
    if re.sub(r'[.,;\s]+','',a.casefold())!=re.sub(r'[.,;\s]+','',b.casefold()):
        return len(normalized(a))>=18
    return True


def position_matches(a,b):
    if a is None or b is None: return True
    ax0,ax1,ay0,ay1=a; bx0,bx1,by0,by1=b
    return (abs((ax0+ax1-bx0-bx1)/2)<=max(ax1-ax0,bx1-bx0)*.5+12
            and abs((ay0+ay1-by0-by1)/2)<=max(ay1-ay0,by1-by0)*1.3+8)


def continuation(previous,current):
    old,new=previous.strip(),current.strip()
    if old==new:return None
    old_key,new_key=normalized(old),normalized(new)
    old_words=[normalized(w) for w in re.findall(r"[\w'’]+",old)]
    new_words=[normalized(w) for w in re.findall(r"[\w'’]+",new)]
    old_protected,new_protected=protections(old),protections(new)
    unchanged_protected=(old_protected[0]==new_protected[0]
        and old_protected[1]==new_protected[1][:len(old_protected[1])]
        and old_protected[2]==new_protected[2][:len(old_protected[2])])
    if (len(old_key)>=8 and new_key.startswith(old_key) and len(new_key)>len(old_key)
        and new_words[:len(old_words)]==old_words and unchanged_protected):
        if not re.search(r'[.!?]$',old) or old.endswith('...'):
            return 'extension'
    # A comma and lowercase initial alone cannot establish a shared utterance.
    # Disjoint fragments remain separate so a new statement is never swallowed.
    return None


@dataclass
class Track:
    key: str
    speaker: str
    body: str
    canonical: str
    current_text: str
    confidence: float
    box: tuple | None
    first_seen: float
    last_seen: float
    count: int = 1
    row: int | None = None
    accepted: bool = False
    prefix: str = ''
    last_body: str = ''
    last_text: str = ''
    missed: int = 0
    retired: bool = False


@dataclass
class Observation:
    track: Track
    candidate: Candidate
    reason: str
    new: bool = False
    corrected: bool = False
    dispatch: bool = False


class ActiveSubtitles:
    def __init__(self,hold=.85):
        self.hold=hold
        self.tracks=[]
        self.expired=[]

    def update(self,candidates,now):
        def expired(t):
            return t.retired or now-t.last_seen>self.hold or (t.missed>=2 and len(t.body.split())<=3)
        self.expired=[t for t in self.tracks if expired(t)]
        self.tracks=[t for t in self.tracks if not expired(t)][-16:]
        used=set(); observations=[]
        for c in candidates:
            match=None; relation=None
            for t in sorted(self.tracks,key=lambda t:t.last_seen,reverse=True):
                if t.key in used or t.speaker.casefold()!=c.speaker.casefold() or not position_matches(t.box,c.box): continue
                if equivalent(t.body,c.body):
                    match,relation=t,'duplicate'; break
            if match is None:
                for t in sorted(self.tracks,key=lambda t:t.last_seen,reverse=True):
                    if t.key in used or t.speaker.casefold()!=c.speaker.casefold() or not position_matches(t.box,c.box):continue
                    relation=continuation(t.last_body or t.body,c.body)
                    if relation and now-t.last_seen<=.65:
                        match=t; break
            if match is None:
                t=Track(uuid.uuid4().hex,c.speaker,c.body,c.text,c.text,c.confidence,c.box,now,now)
                self.tracks.append(t)
                reason='pending_confirmation'
            else:
                t=match; t.count+=1; t.last_seen=now; t.box=c.box
                reason=relation
            used.add(t.key)
            t.missed=0
            new=False; corrected=False; dispatch=False
            if match is not None and relation in ('extension','continuation'):
                if relation=='continuation':
                    t.prefix=(t.prefix+(t.last_body or t.body) if t.prefix else (t.last_text or t.current_text))+' '
                # Exact observed fragments are concatenated; no invented wording.
                if t.prefix:
                    t.canonical=t.prefix+c.body
                else: t.canonical=c.text
                t.body=c.body; t.current_text=c.text; t.confidence=c.confidence
                corrected=True; dispatch=t.accepted
            elif match is not None and c.text!=t.current_text:
                # Prefer a complete observed contraction over a damaged spelling;
                # otherwise improve only on a genuinely better OCR confidence.
                def quality(text,score):
                    return (bool(re.search(r"\bI(?:'ve|'ll)\b",text)),score)
                if quality(c.text,c.confidence)>quality(t.current_text,t.confidence):
                    t.current_text=c.text; t.body=c.body; t.confidence=c.confidence
                    t.canonical=t.prefix+c.body if t.prefix else c.text
                    corrected=True; reason='correction'
            if not t.accepted:
                if math.isfinite(c.confidence) and (c.confidence>=.94 or (c.confidence>=.65 and t.count>=2)):
                    t.accepted=True; new=True; dispatch=True
                    reason='high_confidence' if c.confidence>=.94 else 'confirmed'
                elif not math.isfinite(c.confidence) or c.confidence<.65:
                    reason='below_confidence'; t.count=0
            t.last_body=c.body; t.last_text=c.text
            observations.append(Observation(t,c,reason,new,corrected,dispatch))
        # Consecutive absent frames distinguish short genuine repeats from a
        # single OCR dropout. A different utterance in the same slot retires the
        # old track immediately (A -> B -> A must dispatch three times).
        for t in self.tracks:
            if t.key not in used:
                t.missed+=1
                if len(t.body.split())<=3 and any(c.speaker.casefold()==t.speaker.casefold() and position_matches(t.box,c.box)
                       for c in candidates):
                    t.retired=True
        return observations
