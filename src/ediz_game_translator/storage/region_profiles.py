"""Only game names and normalized coordinates enter the profile settings."""
from copy import deepcopy
import re
from ediz_game_translator.capture.region_geometry import valid_region,DEFAULT_REGION

CROP_KEYS=('crop_left','crop_top','crop_right','crop_bottom')


def game_key(game):
    name=re.sub(r'\s+',' ',game.strip())
    if not name or len(name)>100:raise ValueError('Oyun adı 1–100 karakter olmalı.')
    return name.casefold()


def normalize_profiles(profiles):
    if not isinstance(profiles,dict):raise ValueError('OCR profilleri geçersiz.')
    result={}
    for _,entry in profiles.items():
        if not isinstance(entry,dict) or set(entry)!={'name','rect'} or not isinstance(entry['name'],str):
            raise ValueError('OCR profili yalnız oyun adı ve alan içerebilir.')
        key=game_key(entry['name'])
        result[key]=dict(name=entry['name'].strip(),rect=list(valid_region(entry['rect'])))
    return result


def region_for(settings,game):
    profiles=normalize_profiles(settings.get('ocr_regions',{}))
    key=game_key(game)
    if key in profiles:return valid_region(profiles[key]['rect'])
    if key==game_key(settings.get('game','Genel oyun')):
        return valid_region(tuple(float(settings.get(k,d*100))/100 for k,d in zip(CROP_KEYS,DEFAULT_REGION)))
    return DEFAULT_REGION


def with_region(settings,game,rect):
    result=deepcopy(settings)
    profiles=normalize_profiles(settings.get('ocr_regions',{}))
    key=game_key(game);rect=valid_region(rect)
    profiles[key]=dict(name=game.strip(),rect=list(rect))
    result.update(ocr_regions=profiles,game=game.strip())
    result.update(zip(CROP_KEYS,(x*100 for x in rect)))
    return result


def game_names(settings):
    names={key:entry['name'] for key,entry in normalize_profiles(settings.get('ocr_regions',{})).items()}
    name=settings.get('game','Genel oyun')
    names.setdefault(game_key(name),name)
    return sorted(names.values(),key=str.casefold)


def rename_game(settings,old,new):
    old_key,new_key=game_key(old),game_key(new)
    result=with_region(settings,old,region_for(settings,old))
    profiles=result['ocr_regions']
    if new_key!=old_key and new_key in profiles:
        raise ValueError('Bu adda bir oyun zaten var. Başka bir ad seçin.')
    entry=profiles.pop(old_key)
    profiles[new_key]=dict(name=new.strip(),rect=entry['rect'])
    result['game']=new.strip()
    return result
