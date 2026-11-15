"""Normalized ROI geometry; independent of Tk, image size and display DPI."""
from dataclasses import dataclass
import math

DEFAULT_REGION=(0.,.65,1.,.94)
MIN_SIZE=.01
HANDLES=('nw','n','ne','e','se','s','sw','w')


def valid_region(rect):
    if not isinstance(rect,(list,tuple)) or len(rect)!=4:
        raise ValueError('OCR alanı dört koordinat içermeli.')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in rect):
        raise ValueError('OCR koordinatları sonlu sayılar olmalı.')
    l,t,r,b=map(float,rect)
    if not (0<=l<r<=1 and 0<=t<b<=1 and r-l>=MIN_SIZE-1e-9 and b-t>=MIN_SIZE-1e-9):
        raise ValueError('Alan görüntü içinde olmalı ve her boyutta en az %1 olmalı.')
    return l,t,r,b


@dataclass(frozen=True)
class Viewport:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def fit(cls,cw,ch,iw,ih):
        if min(cw,ch,iw,ih)<=0:raise ValueError('Invalid viewport size')
        scale=min(cw/iw,ch/ih)
        w,h=iw*scale,ih*scale
        return cls((cw-w)/2,(ch-h)/2,w,h)

    def point(self,nx,ny):
        return self.x+nx*self.width,self.y+ny*self.height

    def inverse(self,x,y):
        return max(0,min(1,(x-self.x)/self.width)),max(0,min(1,(y-self.y)/self.height))

    def rect(self,rect):
        l,t,r,b=rect
        return *self.point(l,t),*self.point(r,b)


def handle_points(rect):
    l,t,r,b=rect; x,y=(l+r)/2,(t+b)/2
    return dict(zip(HANDLES,((l,t),(x,t),(r,t),(r,y),(r,b),(x,b),(l,b),(l,y))))


def hit_test(view,rect,x,y,radius=9):
    for name,point in handle_points(rect).items():
        px,py=view.point(*point)
        if abs(x-px)<=radius and abs(y-py)<=radius:return name
    l,t,r,b=view.rect(rect)
    return 'move' if l<=x<=r and t<=y<=b else None


def drag(rect,mode,dx,dy):
    l,t,r,b=rect
    if mode=='move':
        dx=max(-l,min(1-r,dx));dy=max(-t,min(1-b,dy))
        return valid_region((l+dx,t+dy,r+dx,b+dy))
    if mode not in HANDLES:raise ValueError('Invalid handle')
    if 'w' in mode:l=max(0,min(r-MIN_SIZE,l+dx))
    if 'e' in mode:r=min(1,max(l+MIN_SIZE,r+dx))
    if 'n' in mode:t=max(0,min(b-MIN_SIZE,t+dy))
    if 's' in mode:b=min(1,max(t+MIN_SIZE,b+dy))
    return valid_region((l,t,r,b))


class RegionDraft:
    def __init__(self,rect):
        self.rect=valid_region(rect)
        self.history=[]

    def change(self,rect):
        rect=valid_region(rect)
        if rect!=self.rect:
            self.history.append(self.rect)
            self.history=self.history[-50:]
            self.rect=rect

    def undo(self):
        if self.history:self.rect=self.history.pop()

    def reset(self):
        self.change(DEFAULT_REGION)
