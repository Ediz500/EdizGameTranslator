"""Bounded active subtitle tracking; no global fuzzy translation memory."""
from dataclasses import dataclass
import re
import uuid
import math

from ediz_game_translator.core import clean_ocr

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


# --- Stage 1: OCR-noise classes (comparison keys only; raw OCR is never rewritten) ---
# A space can carry meaning: these joins/splits are real differences, not OCR noise.
SPACE_MEANING={'nowhere':'now here','apart':'a part','already':'all ready','along':'a long','alone':'a lone',
    'anymore':'any more','everyday':'every day','maybe':'may be','into':'in to','sometime':'some time',
    'anyone':'any one','awhile':'a while','altogether':'all together','nobody':'no body','onto':'on to',
    'someday':'some day','everyone':'every one','anyway':'any way','cannot':'can not'}
# Dropping the apostrophe turns these contractions into different real words.
APOSTROPHE_WORDS={'well','shell','hell','ill','wed','shed','were','its','cant','wont','id','lets','hed','whore'}
NEGATIONS={'no','not','never','none','nothing','nobody','nowhere','neither','nor','cannot','without'}


def _words(text):
    text=comparison_glyphs(text).casefold().replace('’',"'").replace('‘',"'")
    return re.findall(r"[a-z0-9|']+",text)


def _fold(word):
    """Symmetric OCR glyph fold of one comparison token (l/1/| -> i, 0 -> o in words)."""
    word=word.replace("'",'')
    if any(c.isalpha() for c in word):
        word=word.translate(str.maketrans({'l':'i','1':'i','|':'i','0':'o'}))
        word=re.sub(r'i{2,}','i',word)
    return word


def _negation_count(words):
    return sum(w.replace("'",'') in NEGATIONS or w.endswith("n't") or
               (w.endswith('nt') and w[:-2] in ('can','don','won','didn','doesn','isn','aren','wasn','weren',
                'shouldn','wouldn','couldn','hasn','haven','hadn','mustn','ain'))
               for w in words)


def noise_variant(a,b):
    """Return the OCR-noise class ('format'/'spacing'/'glyph') if b is a pure OCR misreading
    of a (or vice versa), else None. Protected meaning (digits, negation, names, question,
    meaningful spaces, apostrophe words in short lines) is never merged."""
    wa,wb=_words(a),_words(b)
    if not wa or not wb:return None
    fa,fb=[_fold(w) for w in wa],[_fold(w) for w in wb]
    if ''.join(fa)!=''.join(fb):return None
    if len(''.join(fa))<4 and [w.replace("'",'') for w in wa]!=[w.replace("'",'') for w in wb]:return None
    digits=lambda ws:[w for w in ws if re.fullmatch(r'\d+',w)]
    if digits(wa)!=digits(wb):return None
    if ('?' in a)!=('?' in b):return None
    na=max(_negation_count(wa),_negation_count(_resegment(wa,wb)))
    nb=max(_negation_count(wb),_negation_count(_resegment(wb,wa)))
    if na!=nb:return None
    joined_a,joined_b=' '.join(w.replace("'",'') for w in wa),' '.join(w.replace("'",'') for w in wb)
    for joined,apart in SPACE_MEANING.items():
        if (re.search(rf'\b{joined}\b',joined_a) and re.search(rf'\b{apart}\b',joined_b)) or \
           (re.search(rf'\b{joined}\b',joined_b) and re.search(rf'\b{apart}\b',joined_a)):return None
    ambiguous=any(w.replace("'",'') in APOSTROPHE_WORDS and ("'" in w) != ("'" in v)
                  for x,y in ((wa,wb),(wb,wa)) for w in x for v in y if w.replace("'",'')==v.replace("'",''))
    if ambiguous and min(len(wa),len(wb))<6:return None
    if [w.replace("'",'') for w in wa]==[w.replace("'",'') for w in wb]:return 'format'
    if fa==fb:return 'glyph'
    return 'spacing'


def _resegment(words,reference):
    """Split OCR-joined tokens ('notsure') along the reference's word boundaries."""
    ref=[_fold(w) for w in reference];out=[]
    for w in words:
        f=_fold(w);parts=[]
        for r in ref:
            if f.startswith(r) and r and len(r)<len(f):
                rest=f[len(r):]
                if rest in ref:parts=[next(x for x in reference if _fold(x)==r),next(x for x in reference if _fold(x)==rest)];break
        out.extend(parts or [w])
    return out


def degraded_reading(canonical,reading):
    """Asymmetric: True if reading is the locked canonical with 1-2 OCR-dropped letters
    (e.g. "I'll e fine" for "I'll be fine") on a long line. Never when the drop changes a
    number, a negation, a question mark or a capitalised name."""
    import difflib
    wa,wb=_words(canonical),_words(reading)
    fa,fb=''.join(_fold(w) for w in wa),''.join(_fold(w) for w in wb)
    if len(fa)<20 or not 1<=len(fa)-len(fb)<=2:return False
    ops=difflib.SequenceMatcher(None,fa,fb,autojunk=False).get_opcodes()
    if any(tag not in ('equal','delete') for tag,*_ in ops):return False
    if [w for w in wa if re.fullmatch(r'\d+',w)]!=[w for w in wb if re.fullmatch(r'\d+',w)]:return False
    if ('?' in canonical)!=('?' in reading):return False
    if _negation_count(wa)!=_negation_count(_resegment(wb,wa)):return False
    names=lambda t:sorted(w.casefold() for w in protections(comparison_glyphs(t))[2])
    return names(canonical)==names(reading)


SUSPICIOUS=re.compile(r"(?<![\w'])(?:l|Il|Ill|lll|l'm|l've|l'll|l'd|Il'm|I'l|l'II)(?![\w'])|[a-z]I[a-z]|[a-z][01][a-z]"
    r"|(?<![\w'])(?:im|ive|dont|didnt|doesnt|isnt|arent|wasnt|youre|theyre|thats|whats)(?![\w'])"
    r"|(?<![\w'])(?:shell|hell|ill|wed)\s+(?:be|have|never|probably|just|always|need)\b")


def reading_quality(text,confidence):
    """Prefer readings without known OCR damage; confidence breaks ties."""
    return (-len(SUSPICIOUS.findall(text)),text.count("'"),confidence)


def strip_speaker_prefix(body,speaker):
    """'Gloria I heard…' (colon lost) -> 'I heard…' when the track's speaker is known."""
    if speaker and body.casefold().startswith(speaker.casefold()+' '):
        return body[len(speaker):].lstrip(' :')
    return body


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
    absent_since: float | None = None
    streak: int = 0
    seen_frame: int = -2
    contested: bool = False
    held_since: float | None = None


@dataclass
class Observation:
    track: Track
    candidate: Candidate
    reason: str
    new: bool = False
    corrected: bool = False
    dispatch: bool = False


def _speaker_compatible(track,candidate):
    """A missing OCR speaker label never splits an utterance; two readable names must agree."""
    return (not track.speaker or not candidate.speaker
            or track.speaker.casefold()==candidate.speaker.casefold())


def _near(track,candidate):
    """Similar enough that a single reading could be OCR damage: needs consecutive evidence."""
    import difflib
    a=''.join(_fold(w) for w in _words(track.body));b=''.join(_fold(w) for w in _words(candidate.body))
    return bool(a and b) and difflib.SequenceMatcher(None,a,b).ratio()>=.6


class ActiveSubtitles:
    # A verified utterance tolerates conflicting single readings for at most this long.
    CONTEST_HOLD=.6

    def __init__(self,hold=.85,*,live=False,debounce=.12):
        self.hold=hold
        self.live=live;self.debounce=debounce
        self.tracks=[]
        self.expired=[]
        self.held=[]
        self.frame_no=0

    def _match(self,c,used,now):
        for t in sorted(self.tracks,key=lambda t:t.last_seen,reverse=True):
            if t.key in used or t.speaker.casefold()!=c.speaker.casefold() or not position_matches(t.box,c.box): continue
            if equivalent(t.body,c.body):
                return t,'duplicate'
        if self.live:
            # Stage 1: pure OCR noise (format/spacing/glyph) of the locked text is the same utterance.
            for t in sorted(self.tracks,key=lambda t:t.last_seen,reverse=True):
                if t.key in used or not _speaker_compatible(t,c) or not position_matches(t.box,c.box):continue
                body=strip_speaker_prefix(c.body,t.speaker) if not c.speaker else c.body
                if equivalent(t.body,body) or noise_variant(t.body,body) or (t.accepted and degraded_reading(t.body,body)):
                    return t,'ocr_variant'
        for t in sorted(self.tracks,key=lambda t:t.last_seen,reverse=True):
            if t.key in used or t.speaker.casefold()!=c.speaker.casefold() or not position_matches(t.box,c.box):continue
            relation=continuation(t.last_body or t.body,c.body)
            if relation and now-t.last_seen<=.65:
                return t,relation
        return None,None

    def update(self,candidates,now):
        def expired(t):
            absent=t.missed>=2 and t.absent_since is not None and now-t.absent_since>=self.debounce
            return t.retired or now-t.last_seen>self.hold or (absent if self.live else t.missed>=2 and len(t.body.split())<=3)
        self.frame_no+=1
        self.expired=[t for t in self.tracks if expired(t)]
        self.tracks=[t for t in self.tracks if not expired(t)][-16:]
        used=set(); observations=[]
        assigned=[]
        for c in candidates:
            match,relation=self._match(c,used,now)
            if match is not None:used.add(match.key)
            assigned.append((c,match,relation))
        for c,match,relation in assigned:
            contested=False
            if match is None:
                t=Track(uuid.uuid4().hex,c.speaker,c.body,c.text,c.text,c.confidence,c.box,now,now)
                self.tracks.append(t)
                reason='pending_confirmation'
                if self.live:
                    # A near-identical reading over a verified utterance may be OCR damage:
                    # it becomes a new utterance only after consecutive confirmation.
                    t.contested=any(o.accepted and not o.retired and o.key not in used and
                                    position_matches(o.box,c.box) and _near(o,c) for o in self.tracks if o is not t)
            else:
                t=match; t.count+=1; t.last_seen=now; t.box=c.box
                reason=relation
            t.streak=t.streak+1 if t.seen_frame==self.frame_no-1 else 1
            t.seen_frame=self.frame_no;t.held_since=None
            used.add(t.key)
            t.missed=0
            t.absent_since=None
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
            elif match is not None and self.live and t.accepted:
                # Canonical lock: once dispatched, OCR variants never change the source
                # text, the job or the Turkish shown for this utterance.
                pass
            elif match is not None and self.live and c.text!=t.current_text:
                # Short verification phase: keep the least damaged reading seen so far.
                if reading_quality(c.text,c.confidence)>reading_quality(t.current_text,t.confidence):
                    t.current_text=c.text; t.body=c.body; t.confidence=c.confidence
                    if not c.speaker and t.speaker:t.current_text=f'{t.speaker}: {c.body}'
                    t.canonical=t.prefix+c.body if t.prefix else t.current_text
                    corrected=True; reason='correction'
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
                ready=math.isfinite(c.confidence) and (c.confidence>=.94 or (c.confidence>=.65 and t.count>=2))
                if ready and self.live:
                    # A damaged first reading or a contested near-variant waits for one
                    # more consecutive observation (~50 ms) before the text is locked.
                    if t.contested and t.streak<2:ready=False;reason='contested_pending'
                    elif t.count<2 and SUSPICIOUS.search(t.current_text):ready=False;reason='verifying_reading'
                if ready:
                    t.accepted=True; new=True; dispatch=True
                    reason='high_confidence' if c.confidence>=.94 else 'confirmed'
                elif not math.isfinite(c.confidence) or c.confidence<.65:
                    reason='below_confidence'; t.count=0
            t.last_body=c.body; t.last_text=c.text
            observations.append(Observation(t,c,reason,new,corrected,dispatch))
        # Consecutive absent frames distinguish short genuine repeats from a
        # single OCR dropout. A different utterance in the same slot retires the
        # old track immediately (A -> B -> A must dispatch three times).
        self.held=[]
        for t in self.tracks:
            if t.key not in used:
                overlapping=[o for o in self.tracks if o is not t and o.key in used and position_matches(t.box,o.box)] if self.live else []
                if self.live and t.accepted and overlapping and not any(o.accepted for o in overlapping):
                    # Only unverified readings overlap: the utterance is still on screen.
                    if t.held_since is None:t.held_since=now
                    if now-t.held_since<=self.CONTEST_HOLD:
                        self.held.append(t);continue
                t.missed+=1
                if t.absent_since is None:t.absent_since=now
                if self.live and t.accepted and overlapping:
                    if any(o.accepted for o in overlapping):t.retired=True
                    continue
                if (self.live or len(t.body.split())<=3) and any((c.speaker.casefold()==t.speaker.casefold() or self.live and t.box is not None and c.box is not None) and position_matches(t.box,c.box)
                       for c in candidates):
                    t.retired=True
        return observations
