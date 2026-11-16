"""Exact, game/speaker/context-scoped lookups; short ambiguous lines never auto-cache."""
from collections import OrderedDict
import json
from pathlib import Path
import threading


class SafeTranslationMemory:
    def __init__(self,game,namespace,pack=None):
        self.game=game;self.namespace=namespace;self.cache=OrderedDict();self.verified={}
        self.lock=threading.Lock()
        if pack:
            data=json.loads(Path(pack).read_text(encoding='utf-8'))
            if data.get('game')!=game or data.get('reviewed') is not True or data.get('languages')!=['en','tr']:
                raise ValueError('Hazır çeviri paketi oyun/dil/inceleme kontrolünü geçemedi.')
            for e in data['entries']:
                context=e.get('context')
                if not isinstance(context,list) or not e.get('speaker') or not e.get('translation'):raise ValueError('Eksik paket bağlamı')
                if len(e['source'].split())<=3 and not context:raise ValueError('Kısa hazır çeviri açık bağlam gerektirir.')
                self.verified[self.key(e['source'],e['speaker'],context)]=e['translation']

    def key(self,source,speaker,context):
        return self.namespace,self.game,speaker,tuple(context),source.strip()

    def lookup(self,source,speaker,context):
        key=self.key(source,speaker,context)
        with self.lock:
            if key in self.verified:return self.verified[key],'verified_pack'
            if len(source.split())>3 and key in self.cache:return self.cache[key],'context_cache'
        return None,None

    def remember(self,source,speaker,context,translation):
        if len(source.split())<=3:return
        with self.lock:
            self.cache[self.key(source,speaker,context)]=translation
            if len(self.cache)>256:self.cache.popitem(last=False)
