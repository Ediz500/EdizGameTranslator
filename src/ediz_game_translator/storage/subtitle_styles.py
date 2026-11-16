"""Validated per-game visual preferences. No translation or dictionary settings."""
from copy import deepcopy
import math
import re
from ediz_game_translator.capture.region_geometry import valid_region
from .region_profiles import game_key

DEFAULT_STYLE=dict(font_size=36,speaker_color='#50E2BE',show_speaker=True,
                   mask_rect=[.11,.78,.89,.94],alignment='center',position='auto')


def valid_style(style):
    if not isinstance(style,dict) or set(style)-set(DEFAULT_STYLE):raise ValueError('Altyazı tasarımında bilinmeyen alan var.')
    result=deepcopy(DEFAULT_STYLE);result.update(style)
    if type(result['font_size']) is not int or not 12<=result['font_size']<=96:raise ValueError('Yazı boyutu 12–96 olmalı.')
    if not isinstance(result['speaker_color'],str) or not re.fullmatch('#[0-9a-fA-F]{6}',result['speaker_color']):raise ValueError('Geçersiz isim rengi.')
    result['speaker_color']=result['speaker_color'].upper()
    if type(result['show_speaker']) is not bool:raise ValueError('İsim görünümü açık/kapalı olmalı.')
    if result['alignment'] not in ('left','center','right') or result['position'] not in ('auto','fixed'):raise ValueError('Geçersiz altyazı hizası/konumu.')
    result['mask_rect']=list(valid_region(result['mask_rect']))
    return result


def normalize_styles(profiles):
    if not isinstance(profiles,dict):raise ValueError('Altyazı profilleri geçersiz.')
    result={}
    for entry in profiles.values():
        if not isinstance(entry,dict) or 'name' not in entry:raise ValueError('Altyazı profili adı eksik.')
        name=entry['name'];key=game_key(name)
        result[key]=dict(name=name.strip(),**valid_style({k:v for k,v in entry.items() if k!='name'}))
    return result


def style_for(settings,game):
    profile=normalize_styles(settings.get('subtitle_profiles',{})).get(game_key(game))
    if profile:return {k:deepcopy(profile[k]) for k in DEFAULT_STYLE}
    result=deepcopy(DEFAULT_STYLE);result['font_size']=int(settings.get('font_size',36))
    return valid_style(result)


def with_style(settings,game,style):
    result=deepcopy(settings);profiles=normalize_styles(result.get('subtitle_profiles',{}))
    profiles[game_key(game)]=dict(name=game.strip(),**valid_style(style))
    result['subtitle_profiles']=profiles
    return result
