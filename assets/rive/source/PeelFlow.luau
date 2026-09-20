--!nocheck
-- One persistent scene. Host-controlled by default; demoMode previews all stages.
-- stage: 0 bottle, 1 imprint, 2 connecting, 3 placed, 4 checking,
--        5 scan complete, 6 research, 7 research complete/cleared.
export type PeelFlow = {
 stage: Input<number>, demoMode: Input<boolean>, reduceMotion: Input<boolean>, motionPaused: Input<boolean>,
 pillShape: Input<number>, pillForm: Input<number>, pillColorA: Input<Color>,
 pillColorB: Input<Color>, twoTone: Input<boolean>, imprintText: Input<string>,
 demoClock: number, demoWasEnabled: boolean,
 clock: number, elapsed: number, lastStage: number, duration: number,
 pose: any, from: any, paths: any, paints: any, cursor: number,
 researchClock: number, exitClock: number, exitCycle: any, exitLeadingVisible: boolean, geometry: any, oldGeometry: any, appearanceTime: number, appearance: any, oldAppearance: any,
}
local C={ink=Color.rgb(43,33,24),orange=Color.rgb(255,159,28),deep=Color.rgb(185,71,0),
 soft=Color.rgb(255,240,217),canvas=Color.rgb(255,252,247),white=Color.rgb(255,255,255),
 teal=Color.rgb(39,107,101),liquid=Color.rgb(229,243,239),muted=Color.rgb(102,88,76),
 red=Color.rgb(198,75,75),green=Color.rgb(110,168,121),blue=Color.rgb(92,143,214)}
local PI=math.pi
local function clamp(x) return math.max(0,math.min(1,x)) end
local function smooth(x) x=clamp(x);return x*x*(3-2*x) end
local function mix(a,b,t) return a+(b-a)*t end
local function copy(p) local q={};for k,v in p do q[k]=v end;return q end
local function path(self)
 self.cursor+=1
 local p=self.paths[self.cursor]
 if not p then p=Path.new();self.paths[self.cursor]=p else p:reset() end
 return p
end
local function rect(self,x,y,w,h,r)
 local p=path(self);r=math.min(r or 0,w/2,h/2)
 p:moveTo(Vector.xy(x+r,y));p:lineTo(Vector.xy(x+w-r,y));p:quadTo(Vector.xy(x+w,y),Vector.xy(x+w,y+r))
 p:lineTo(Vector.xy(x+w,y+h-r));p:quadTo(Vector.xy(x+w,y+h),Vector.xy(x+w-r,y+h))
 p:lineTo(Vector.xy(x+r,y+h));p:quadTo(Vector.xy(x,y+h),Vector.xy(x,y+h-r))
 p:lineTo(Vector.xy(x,y+r));p:quadTo(Vector.xy(x,y),Vector.xy(x+r,y));p:close();return p
end
local function oval(self,x,y,rx,ry)
 local p=path(self);local k=.5522847498
 p:moveTo(Vector.xy(x+rx,y));p:cubicTo(Vector.xy(x+rx,y+ry*k),Vector.xy(x+rx*k,y+ry),Vector.xy(x,y+ry))
 p:cubicTo(Vector.xy(x-rx*k,y+ry),Vector.xy(x-rx,y+ry*k),Vector.xy(x-rx,y))
 p:cubicTo(Vector.xy(x-rx,y-ry*k),Vector.xy(x-rx*k,y-ry),Vector.xy(x,y-ry))
 p:cubicTo(Vector.xy(x+rx*k,y-ry),Vector.xy(x+rx,y-ry*k),Vector.xy(x+rx,y));p:close();return p
end
local function paint(self,r,p,fill,stroke,width)
 local n=self.cursor*2
 if fill then
  local f=self.paints[n];if not f then f=Paint.with({style='fill',color=fill});self.paints[n]=f else f.color=fill end
  r:drawPath(p,f)
 end
 if stroke then
  local s=self.paints[n+1];if not s then s=Paint.with({style='stroke',color=stroke,thickness=width or 2.5,cap='round',join='round'});self.paints[n+1]=s else s.color=stroke;s.thickness=width or 2.5 end
  r:drawPath(p,s)
 end
end
local function line(self,r,x1,y1,x2,y2,color,w)
 local p=path(self);p:moveTo(Vector.xy(x1,y1));p:lineTo(Vector.xy(x2,y2));paint(self,r,p,nil,color,w)
end
local function transform(r,x,y,scale,angle)
 r:save();r:transform(Mat2D.withTranslation(x,y));r:transform(Mat2D.withRotation(angle or 0));r:transform(Mat2D.withScale(scale or 1))
end
local function bottle(self,r,x,y,scale,angle,cap)
 transform(r,x,y,scale,angle)
 local p=path(self);p:moveTo(Vector.xy(-38,-64));p:lineTo(Vector.xy(38,-64));p:lineTo(Vector.xy(38,-53))
 p:cubicTo(Vector.xy(38,-44),Vector.xy(54,-38),Vector.xy(54,-20));p:lineTo(Vector.xy(54,91))
 p:quadTo(Vector.xy(54,107),Vector.xy(38,107));p:lineTo(Vector.xy(-38,107));p:quadTo(Vector.xy(-54,107),Vector.xy(-54,91))
 p:lineTo(Vector.xy(-54,-20));p:cubicTo(Vector.xy(-54,-38),Vector.xy(-38,-44),Vector.xy(-38,-53));p:close()
 paint(self,r,p,C.orange,C.ink,2.5)
 p=path(self);p:moveTo(Vector.xy(43,-34));p:quadTo(Vector.xy(53,-26),Vector.xy(53,-16));p:lineTo(Vector.xy(53,91));p:quadTo(Vector.xy(53,106),Vector.xy(36,106));p:lineTo(Vector.xy(24,106));p:quadTo(Vector.xy(42,101),Vector.xy(42,87));p:close();paint(self,r,p,C.deep,nil)
 p=path(self);p:moveTo(Vector.xy(-42,-19));p:quadTo(Vector.xy(-42,-29),Vector.xy(-32,-34));paint(self,r,p,nil,C.soft,5)
 paint(self,r,rect(self,-53,-5,106,76,5),C.canvas,C.ink,2.5)
 line(self,r,-37,14,16,14,C.ink,5);line(self,r,-37,31,28,31,C.ink,4);line(self,r,-37,48,5,48,C.ink,4)
 paint(self,r,rect(self,-47,-75-cap,94,30,8),C.canvas,C.ink,2.5)
 for j=0,5 do line(self,r,-33+j*14,-66-cap,-33+j*14,-54-cap,C.muted,2.5) end
 r:restore()
end
local function geometry(shape,form)
 if form>=.5 then return {70,34,36} end
 if shape>=1.5 then return {70,32,35} end
 if shape>=.5 then return {50,50,0} end
 return {70,35,0}
end
local glyphs={
 ['0']={14,17,19,21,25,17,14},['1']={4,12,4,4,4,4,14},['2']={14,17,1,2,4,8,31},['3']={30,1,1,14,1,1,30},['4']={2,6,10,18,31,2,2},['5']={31,16,16,30,1,1,30},['6']={14,16,16,30,17,17,14},['7']={31,1,2,4,8,8,8},['8']={14,17,17,14,17,17,14},['9']={14,17,17,15,1,1,14},
 A={14,17,17,31,17,17,17},B={30,17,17,30,17,17,30},C={14,17,16,16,16,17,14},D={30,17,17,17,17,17,30},E={31,16,16,30,16,16,31},F={31,16,16,30,16,16,16},G={14,17,16,23,17,17,15},H={17,17,17,31,17,17,17},I={14,4,4,4,4,4,14},J={7,2,2,2,18,18,12},K={17,18,20,24,20,18,17},L={16,16,16,16,16,16,31},M={17,27,21,21,17,17,17},N={17,25,21,19,17,17,17},O={14,17,17,17,17,17,14},P={30,17,17,30,16,16,16},Q={14,17,17,17,21,18,13},R={30,17,17,30,20,18,17},S={15,16,16,14,1,1,30},T={31,4,4,4,4,4,4},U={17,17,17,17,17,17,14},V={17,17,17,17,17,10,4},W={17,17,17,21,21,27,17},X={17,17,10,4,10,17,17},Y={17,17,10,4,4,4,4},Z={31,1,2,4,8,16,31},
 a={0,0,14,1,15,17,15},b={16,16,30,17,17,17,30},c={0,0,14,17,16,17,14},d={1,1,15,17,17,17,15},e={0,0,14,17,31,16,14},f={6,9,8,28,8,8,8},g={0,0,15,17,15,1,14},h={16,16,30,17,17,17,17},i={4,0,12,4,4,4,14},j={2,0,6,2,2,18,12},k={16,16,18,20,24,20,18},l={12,4,4,4,4,4,14},m={0,0,26,21,21,21,21},n={0,0,30,17,17,17,17},o={0,0,14,17,17,17,14},p={0,0,30,17,30,16,16},q={0,0,15,17,15,1,1},r={0,0,22,25,16,16,16},s={0,0,15,16,14,1,30},t={8,8,28,8,8,9,6},u={0,0,17,17,17,19,13},v={0,0,17,17,17,10,4},w={0,0,17,17,21,21,10},x={0,0,17,10,4,10,17},y={0,0,17,17,15,1,14},z={0,0,31,2,4,8,31},
 ['-']={0,0,0,31,0,0,0},['.']={0,0,0,0,0,6,6},['/']={1,2,2,4,8,8,16},['+']={0,4,4,31,4,4,0},[' ']={0,0,0,0,0,0,0},['(']={2,4,8,8,8,4,2},[')']={8,4,2,2,2,4,8},['_']={0,0,0,0,0,0,31}
}
local function contrasting(color)
 local brightness=.2126*Color.red(color)+.7152*Color.green(color)+.0722*Color.blue(color)
 return brightness<140 and C.white or C.ink
end
local function imprint(self,r,text,color,capsule)
 if #text==0 or #text>(capsule and 5 or 10) then return end
 for i=1,#text do if not glyphs[string.sub(text,i,i)] then return end end
 local size=1.4;local width=(#text*6-1)*size;local origin=-width/2-(capsule and 34 or 0)
 local q=path(self)
 for i=1,#text do
  local rows=glyphs[string.sub(text,i,i)]
  for row=1,7 do
   for col=0,4 do
    if bit32.band(rows[row],bit32.lshift(1,4-col))~=0 then
     local x=origin+((i-1)*6+col)*size;local y=-4.9+(row-1)*size
     q:moveTo(Vector.xy(x,y));q:lineTo(Vector.xy(x+size,y));q:lineTo(Vector.xy(x+size,y+size));q:lineTo(Vector.xy(x,y+size));q:close()
    end
   end
  end
 end
 paint(self,r,q,color,nil)
end
local function pillPath(self)
 local rx,ry,flat=self.geometry[1],self.geometry[2],self.geometry[3]
 local k=.5522847498;local side=rx-flat;local q=path(self)
 q:moveTo(Vector.xy(-flat,-ry));q:lineTo(Vector.xy(flat,-ry))
 q:cubicTo(Vector.xy(flat+side*k,-ry),Vector.xy(rx,-ry*k),Vector.xy(rx,0))
 q:cubicTo(Vector.xy(rx,ry*k),Vector.xy(flat+side*k,ry),Vector.xy(flat,ry));q:lineTo(Vector.xy(-flat,ry))
 q:cubicTo(Vector.xy(-flat-side*k,ry),Vector.xy(-rx,ry*k),Vector.xy(-rx,0))
 q:cubicTo(Vector.xy(-rx,-ry*k),Vector.xy(-flat-side*k,-ry),Vector.xy(-flat,-ry));q:close();return q
end
local function pillFills(self,r,appearance)
 paint(self,r,rect(self,-80,-60,160,120,0),appearance.a,nil)
 if appearance.form>=.5 and appearance.two then paint(self,r,rect(self,0,-60,80,120,0),appearance.b,nil) end
 if appearance.form>=.5 then line(self,r,0,-50,0,50,contrasting(appearance.a),1.5) end
 imprint(self,r,appearance.text,contrasting(appearance.a),appearance.form>=.5)
end
local function pill(self,r,x,y,s,angle,scan)
 transform(r,x,y,s,angle)
 local silhouette=pillPath(self)
 paint(self,r,silhouette,self.appearance.a,C.ink,2.5)
 r:save();r:clipPath(silhouette)
 pillFills(self,r,self.oldAppearance)
 r:save();r:clipPath(rect(self,-81,-61,162,122*clamp(self.appearanceTime/.45),0));pillFills(self,r,self.appearance);r:restore()
 if scan then line(self,r,-80,scan,80,scan,C.teal,2.5) end
 r:restore()
 paint(self,r,pillPath(self),nil,C.ink,2.5)
 if contrasting(self.appearance.a)==C.white then
  r:save();r:transform(Mat2D.withScale(.95));local edge=pillPath(self);paint(self,r,edge,nil,C.white,1.4);r:restore()
 end
 r:restore()
end
local function phone(self,r,p,t)
 transform(r,p.phoneX,227,1,math.rad(7))
 paint(self,r,rect(self,-45,-80,90,160,17),C.ink,C.ink,2.5)
 paint(self,r,rect(self,-38,-72,76,144,11),C.white,nil)
 paint(self,r,rect(self,-14,-67,28,5,2.5),C.ink,nil)
 local screen=rect(self,-32,-44,64,95,5);r:save();r:clipPath(screen)
 bottle(self,r,-p.preview*90,0,.34,0,0)
 pill(self,r,90*(1-p.preview),0,.30,0,nil)
 if p.preview<.01 then line(self,r,-16,-2+20*(.5-.5*math.cos(t*PI/2)),16,-2+20*(.5-.5*math.cos(t*PI/2)),C.teal,2) end
 r:restore()
 local d=2*(.5-.5*math.cos(t*PI/2))
 for _,a in {{-27+d,-42+d,1,1},{27-d,-42+d,-1,1},{-27+d,49-d,1,-1},{27-d,49-d,-1,-1}} do
  local q=path(self);q:moveTo(Vector.xy(a[1]+9*a[3],a[2]));q:lineTo(Vector.xy(a[1],a[2]));q:lineTo(Vector.xy(a[1],a[2]+11*a[4]));paint(self,r,q,nil,C.teal,2.5)
 end
 line(self,r,-10,64,10,64,C.muted,2.5);r:restore()
end
local function waterLines(self,r,t)
 local phase=t*2*PI/(self.lastStage==4 and 6 or 8)
 for j=0,1 do
  local q=path(self)
  for i=0,36 do
   local u=i/36;local angle=phase+j*PI+u*PI*1.15
   local point=Vector.xy((35+52*u)*math.cos(angle),(10+15*u)*math.sin(angle))
   if i==0 then q:moveTo(point) else q:lineTo(point) end
  end
  paint(self,r,q,nil,C.teal,2)
 end
end
local function deviceBack(self,r,p,t)
 transform(r,p.deviceX,p.deviceY,p.deviceS,p.deviceR)
 paint(self,r,oval(self,0,0,116,42),C.canvas,C.ink,2.5)
 local liquid=oval(self,0,0,102,31);paint(self,r,liquid,C.liquid,C.teal,2)
 -- LEDs are built into the rear rim: fixed position, color, and brightness.
 for j,angle in {-2.45,-PI/2,-.69} do
  local x=109*math.cos(angle);local y=36*math.sin(angle)
  line(self,r,x-6,y,x+6,y,({C.red,C.green,C.blue})[j],4)
 end
 r:restore()
end
local function waterFront(self,r,p,t)
 -- The opaque surface fully hides the pill after it falls into the water.
 -- Its appearance stays intact underneath for host-driven continuity.
 transform(r,p.deviceX,p.deviceY,p.deviceS,p.deviceR)
 local liquid=oval(self,0,0,102,31)
 paint(self,r,liquid,C.liquid,C.teal,2)
 r:save();r:clipPath(liquid);waterLines(self,r,t);r:restore()
 r:restore()
end
local function deviceFront(self,r,p)
 transform(r,p.deviceX,p.deviceY,p.deviceS,p.deviceR)
 local q=path(self);q:moveTo(Vector.xy(-116,0));q:cubicTo(Vector.xy(-102,49),Vector.xy(102,49),Vector.xy(116,0));q:cubicTo(Vector.xy(116,80),Vector.xy(72,113),Vector.xy(0,113));q:cubicTo(Vector.xy(-72,113),Vector.xy(-116,80),Vector.xy(-116,0));q:close();paint(self,r,q,C.orange,C.ink,2.5)
 q=path(self);q:moveTo(Vector.xy(96,24));q:quadTo(Vector.xy(93,96),Vector.xy(4,109));q:cubicTo(Vector.xy(67,113),Vector.xy(114,75),Vector.xy(114,7));q:close();paint(self,r,q,C.deep,nil)
 q=path(self);q:moveTo(Vector.xy(-94,38));q:quadTo(Vector.xy(-88,58),Vector.xy(-75,65));paint(self,r,q,nil,C.soft,5)
 for _,v in {{-65,86,-61,89},{-41,95,-37,96},{39,88,43,86},{62,74,65,71}} do line(self,r,v[1],v[2],v[3],v[4],C.deep,3) end
 r:restore()
end
local function orangeTop(self,r,p,t)
 transform(r,p.deviceX,p.deviceY,p.deviceS,p.deviceR)
 r:transform(Mat2D.withTranslation(0,-1000*(1-p.close)))
 local q=path(self);q:moveTo(Vector.xy(-116,0));q:cubicTo(Vector.xy(-116,-65),Vector.xy(-72,-109),Vector.xy(0,-109));q:cubicTo(Vector.xy(72,-109),Vector.xy(116,-65),Vector.xy(116,0));q:cubicTo(Vector.xy(102,50),Vector.xy(-102,50),Vector.xy(-116,0));q:close();paint(self,r,q,C.orange,C.ink,2.5)
 q=path(self);q:moveTo(Vector.xy(-90,-33));q:quadTo(Vector.xy(-83,-62),Vector.xy(-59,-73));paint(self,r,q,nil,C.soft,6)
 line(self,r,-3,-107,1,-127,C.ink,4)
 transform(r,0,-120,1,math.rad(3*math.sin(t*2*PI/5)))
 q=path(self);q:moveTo(Vector.xy(0,0));q:quadTo(Vector.xy(7,-29),Vector.xy(43,-18));q:quadTo(Vector.xy(35,8),Vector.xy(0,0));q:close();paint(self,r,q,C.teal,C.ink,2.5);r:restore()
 for _,v in {{-37,-83,-33,-85},{30,-76,35,-74},{67,-50,70,-46}} do line(self,r,v[1],v[2],v[3],v[4],C.deep,3) end
 r:restore()
end
local function miniOrange(self,r,x,y,angle)
 transform(r,x,y,1,angle)
 paint(self,r,oval(self,0,0,15,15),C.orange,C.ink,2)
 local q=path(self);q:moveTo(Vector.xy(-2,-15));q:quadTo(Vector.xy(0,-25),Vector.xy(11,-22));q:quadTo(Vector.xy(10,-14),Vector.xy(-2,-15));q:close();paint(self,r,q,C.teal,C.ink,1.5)
 line(self,r,-11,-2,-9,-5,C.deep,2);line(self,r,8,6,5,8,C.deep,2);r:restore()
end
local function research(self,r,p,t,foreground)
 transform(r,p.researchX,0,1,0)
 if not foreground then
 local q
 for _,baseline in {160,287} do
  q=path(self);q:moveTo(Vector.xy(-35,baseline))
  for i=1,60 do local u=i/60;q:lineTo(Vector.xy(-35+435*u,baseline+16*math.sin(u*2*PI))) end
  paint(self,r,q,nil,C.teal,3)
 end
 q=path(self);q:moveTo(Vector.xy(75,162));q:quadTo(Vector.xy(122,205),Vector.xy(177,279));q:quadTo(Vector.xy(224,233),Vector.xy(271,152));paint(self,r,q,nil,C.teal,3)
 -- A 3 s offset keeps at least one orange visible at either clipped reset.
 for j=2,2 do
  local time=self.researchClock;local cycle=math.floor(time/6);local u=(time%6)/6
  local x=-35+435*u;local y=(j==1 and 160 or 287)+16*math.sin(u*2*PI)
  local visible=self.lastStage~=7 or cycle==self.exitCycle[j]
  if visible then miniOrange(self,r,x,y,(x+35)/15) end
 end
 else
 -- Cards are foreground occluders; they remain completely stationary.
 for _,v in {{38,117},{233,98},{143,290}} do
  local x,y=v[1],v[2];paint(self,r,rect(self,x,y,72,86,9),C.white,C.ink,2.5)
  line(self,r,x+1,y+18,x+71,y+18,C.muted,2)
  for j=0,3 do line(self,r,x+12,y+31+j*11,x+({46,56,50,35})[j+1],y+31+j*11,C.muted,2.5) end
 end
 end
 r:restore()
end
local function target(stage)
 local p={bottleX=-190,bottleY=188,bottleR=0,cap=0,phoneX=490,preview=1,
 pillX=182,pillY=170,pillS=.6,pillR=0,deviceX=182,deviceY=266,deviceS=1,deviceR=0,close=0,researchX=520}
 if stage==0 then p.bottleX=132;p.phoneX=252;p.preview=0;p.pillX=132;p.pillY=180;p.pillS=.2;p.deviceY=620
 elseif stage==1 then p.phoneX=270;p.pillX=158;p.pillY=180;p.pillS=1;p.deviceY=620
 elseif stage==2 then -- pill waits above the opening
 elseif stage==3 or stage==4 then p.pillY=276
 elseif stage==5 then p.pillY=276;p.close=1
 elseif stage==6 then p.pillY=276;p.close=1;p.deviceX=-100;p.deviceY=160;p.deviceS=.13;p.researchX=0
 elseif stage==7 then p.deviceX=-100;p.deviceS=.13;p.close=1;p.researchX=-520 end
 return p
end
local function appearance(self)
 return {shape=self.pillShape,form=self.pillForm,a=Color.alpha(self.pillColorA,255),b=Color.alpha(self.pillColorB,255),two=self.twoTone,text=self.imprintText}
end
-- Demo-only dwell times include each transition and at least one full idle loop.
-- The 52-second demo repeats; stage remains the host's untouched input.
local function demoStage(clock)
 local time=clock%52
 for i,duration in {5,6,6,6,7,7,13,2} do
  if time<duration then return i-1 end
  time-=duration
 end
 return 0
end
local function update(self)
 if self.demoMode~=self.demoWasEnabled then
  self.demoClock=0;self.demoWasEnabled=self.demoMode
 end
 local incoming=appearance(self);local changed=false
 for k,v in incoming do if self.appearance[k]~=v then changed=true end end
 if changed then
  self.oldAppearance=self.appearance;self.appearance=incoming;self.appearanceTime=0;self.oldGeometry={self.geometry[1],self.geometry[2],self.geometry[3]}
  if self.lastStage<1 then self.appearanceTime=.45;self.oldAppearance=incoming end
 end
 local stage=self.demoMode and demoStage(self.demoClock) or math.max(0,math.min(7,math.floor(self.stage+.5)))
 if stage~=self.lastStage then
  self.from=copy(self.pose);self.lastStage=stage;self.elapsed=0
  self.duration=({.8,1.5,.75,.8,.5,1.4,.9,.65})[stage+1]
  if stage==6 then self.researchClock=0 end
  if stage==7 then
   local x=-35+435*((self.researchClock%6)/6)
   self.exitCycle={math.floor((self.researchClock+3)/6),(x<=-15 or x>=379) and -1 or math.floor(self.researchClock/6)}
   self.exitLeadingVisible=self.pose.deviceX>-15 and self.pose.deviceX<379
   self.exitClock=self.researchClock
  end
 end
end
local function advance(self,seconds)
 update(self)
 if self.demoMode and not self.motionPaused then
  self.demoClock+=seconds;update(self)
 end
 local stop=self.reduceMotion or self.motionPaused
 self.appearanceTime=stop and .45 or math.min(.45,self.appearanceTime+seconds)
 local g=geometry(self.pillShape,self.pillForm);local appearanceMix=smooth(self.appearanceTime/.45)
 for i=1,3 do self.geometry[i]=mix(self.oldGeometry[i],g[i],appearanceMix) end
 if stop then
  if self.elapsed<self.duration or self.reduceMotion then self.pose=target(self.lastStage);self.elapsed=self.duration end
  if self.lastStage==6 then self.pose.deviceX=182.5;self.pose.deviceY=160;self.pose.deviceS=15/116 end
  if self.lastStage>=5 then local p=self.pose;p.pillX=p.deviceX;p.pillY=p.deviceY+10*p.deviceS;p.pillS=.6*p.deviceS;p.pillR=p.deviceR end
  return true
 end
 self.clock+=seconds;self.elapsed+=seconds
 if self.lastStage>=6 then self.researchClock+=seconds end
 local d=target(self.lastStage);local u=clamp(self.elapsed/self.duration);local e=smooth(u)
 if self.lastStage==6 then
  local phase=((self.researchClock+3)%6)/6
  d.deviceX=-35+435*phase;d.deviceY=160+16*math.sin(phase*2*PI);d.deviceS=15/116;d.deviceR=(435*phase-217.5)/15
 end
 local p={};for k,v in d do p[k]=mix(self.from[k],v,e) end
 if self.lastStage==7 then
  p=copy(self.from);p.researchX=mix(self.from.researchX,-520,e)
  p.deviceX=self.from.deviceX+(p.researchX-self.from.researchX)+math.min(self.elapsed,self.duration)*72.5
  p.deviceY=self.from.deviceY;p.deviceR=self.from.deviceR+math.min(self.elapsed,self.duration)*72.5/15
  if self.elapsed>=self.duration or not self.exitLeadingVisible then p.deviceX=-600 end
 end
 if self.lastStage==1 and u<1 then
  local a=smooth(math.min(1,u*2));p.pillY=mix(self.from.pillY,98,a)
  if u>.35 then p.pillY=mix(98,180,smooth((u-.35)/.65)) end
  p.cap=math.sin(PI*u)*25;p.bottleR=math.sin(PI*u)*math.rad(9)
 end
 if self.lastStage==5 then p.close=smooth((u-.35)/.65) end
 if u>=1 then
  local t=self.elapsed-self.duration
  if self.lastStage==0 then p.phoneX-=2-2*math.cos(t*PI/2)
  elseif self.lastStage==1 or self.lastStage==2 then p.pillY+=1.5*math.sin(t*2*PI/(self.lastStage==1 and 4 or 5))
  elseif self.lastStage==3 then p.pillX+=3*math.sin(t*2*PI/5)
  elseif self.lastStage==4 then p.pillX+=3*math.sin(t*2*PI/6);p.pillR=math.rad(5)*math.sin(t*2*PI/6) end
 end
 if self.lastStage>=5 then p.pillX=p.deviceX;p.pillY=p.deviceY+10*p.deviceS;p.pillS=.6*p.deviceS;p.pillR=p.deviceR end
 self.pose=p;return true
end
local function draw(self,r)
 self.cursor=0
 r:save();r:clipPath(rect(self,0,0,364,416,0))
 local p=self.pose;local t=self.reduceMotion and 0 or self.clock
 research(self,r,p,t,false)
 deviceBack(self,r,p,t)
 local scan=nil
 if self.lastStage==1 and self.elapsed>=self.duration then scan=-35+70*(.5-.5*math.cos(t*PI/2)) end
 local submerged=self.lastStage>=3 and p.pillY>=p.deviceY
 if not submerged then pill(self,r,p.pillX,p.pillY,p.pillS,p.pillR,scan) end
 waterFront(self,r,p,t)
 deviceFront(self,r,p)
 orangeTop(self,r,p,t)
 research(self,r,p,t,true)
 -- The initial pill is physically hidden behind the bottle, never faded.
 bottle(self,r,p.bottleX,p.bottleY,1,p.bottleR,p.cap)
 phone(self,r,p,t)
 r:restore()
end
local function init(self)
 self.pose=target(0);self.pose.bottleX=-100;self.pose.pillX=-100;self.pose.phoneX=490
 self.appearance=appearance(self);self.oldAppearance=self.appearance;self.geometry=geometry(self.pillShape,self.pillForm);self.oldGeometry={self.geometry[1],self.geometry[2],self.geometry[3]}
 self.from=copy(self.pose);self.lastStage=-1;update(self);return true
end
return function(): Node<PeelFlow>
 return {stage=0,demoMode=false,reduceMotion=false,motionPaused=false,pillShape=0,pillForm=0,
 pillColorA=Color.rgb(245,241,232),pillColorB=Color.rgb(245,241,232),twoTone=false,imprintText='',
 demoClock=0,demoWasEnabled=false,clock=0,elapsed=0,lastStage=-1,duration=.8,pose={},from={},paths={},paints={},cursor=0,
 researchClock=0,exitClock=0,exitCycle={0,0},exitLeadingVisible=true,geometry={70,35,0},oldGeometry={70,35,0},appearanceTime=.45,appearance={},oldAppearance={},init=init,update=update,advance=advance,draw=draw}
end
