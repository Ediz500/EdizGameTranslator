"""Validation only: fail if a cloud SDK is imported, even when installed."""
import importlib.abc
import sys


class NoCloudImports(importlib.abc.MetaPathFinder):
    roots={'openai','httpx2','httpcore2','jiter'}
    def __init__(self):self.attempts=[]
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in self.roots:
            self.attempts.append(fullname)
            raise AssertionError('Forbidden cloud SDK import: '+fullname)
    def __enter__(self):
        if any(name.split('.')[0] in self.roots for name in sys.modules):
            raise AssertionError('Cloud SDK already loaded before guarded validation')
        sys.meta_path.insert(0,self);return self
    def __exit__(self,*args):
        sys.meta_path.remove(self)
        if self.attempts and args[0] is None:raise AssertionError('Cloud import attempted during local operation')
