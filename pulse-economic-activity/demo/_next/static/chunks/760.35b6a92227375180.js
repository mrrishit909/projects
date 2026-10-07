"use strict";(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[760],{5760:(e,t,a)=>{a.r(t),a.d(t,{OUTAGE_PORT:()=>S,camFor:()=>h,default:()=>E});var r=a(4568),o=a(5319),n=a(6546),l=a(7620),i=a(6339),u=a(2137),s=a(328),f=a(1767),c=a(4591);let m=`
  const float DEG = 0.017453292519943295;
  uniform float uMorph;
  vec3 unitVec(float lat, float lon) { return vec3(cos(lat * DEG) * cos(lon * DEG), sin(lat * DEG), -cos(lat * DEG) * sin(lon * DEG)); }
  vec3 projectP(float lat, float lon, float h) {
    vec3 g = unitVec(lat, lon) * (1.0 + h);
    vec3 f = vec3(lon * DEG, lat * DEG, h);
    return mix(g, f, uMorph);
  }
  // point at fraction t of the great circle; longitude unwrapped relative to the start so the flat map draws it continuously
  vec2 arcLatLon(vec4 lane, float t) {
    vec3 a = unitVec(lane.x, lane.y), b = unitVec(lane.z, lane.w);
    float d = acos(clamp(dot(a, b), -1.0, 1.0));
    vec3 p = d < 1e-5 ? a : (sin((1.0 - t) * d) * a + sin(t * d) * b) / sin(d);
    float lat = asin(clamp(p.y, -1.0, 1.0)) / DEG, lon = atan(-p.z, p.x) / DEG;
    float dl = lon - lane.y;
    lon = lane.y + dl - 360.0 * floor((dl + 180.0) / 360.0);
    return vec2(lat, lon);
  }
  float arcAngle(vec4 lane) { return acos(clamp(dot(unitVec(lane.x, lane.y), unitVec(lane.z, lane.w)), -1.0, 1.0)); }
  vec3 arcPoint(vec4 lane, float t) { vec2 ll = arcLatLon(lane, t); return projectP(ll.x, ll.y, 0.16 * arcAngle(lane) / 3.14159 * sin(3.14159 * t) + 0.004); }
  vec3 sideAt(vec4 lane, float t) {
    vec3 p = arcPoint(lane, t), q = arcPoint(lane, min(1.0, t + 0.01)), r = arcPoint(lane, max(0.0, t - 0.01));
    vec3 up = normalize(mix(normalize(p), vec3(0.0, 0.0, 1.0), uMorph));
    return normalize(cross(q - r, up));
  }`,d="uniform vec4 uLanes[64]; uniform float uWidth[64]; uniform float uMask[64]; uniform vec3 uColor[64];";function v(e,t){return new i.BKk({transparent:0!==t,uniforms:{uDay:{value:e},uMorph:{value:0},uOffset:{value:t},uDim:{value:0}},vertexShader:`
      ${m}
      uniform float uOffset;
      varying vec2 vUv; varying float vShade;
      void main() {
        float lon = -180.0 + 360.0 * uv.x + uOffset, lat = -90.0 + 180.0 * uv.y;
        vUv = vec2((lon + 180.0) / 360.0, uv.y);
        vec3 p = projectP(lat, lon, 0.0);
        vShade = mix(0.55 + 0.45 * max(0.0, dot(normalize(p), normalize(vec3(0.5, 0.6, 0.6)))), 1.0, uMorph);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,fragmentShader:`
      uniform sampler2D uDay; uniform float uMorph; uniform float uOffset; uniform float uDim;
      varying vec2 vUv; varying float vShade;
      void main() {
        vec3 t = texture2D(uDay, vUv).rgb;
        float g = dot(t, vec3(0.3, 0.59, 0.11));
        vec3 col = (mix(vec3(g), t, 0.35) * 0.5 + vec3(0.012, 0.025, 0.05)) * vShade * (1.0 - 0.45 * uDim);
        float a = uOffset != 0.0 ? smoothstep(0.6, 0.95, uMorph) : 1.0;
        gl_FragColor = vec4(col, a);
      }`})}let p=Math.PI/180;function h(e,t,a,r){let o=(0,u.DY)(e,t),n=[o[0]*a,o[1]*a,o[2]*a,0,0,0],l=[t*p,e*p-.12*a,.95*a,t*p,e*p,0];return n.map((e,t)=>e+(l[t]-e)*r)}let g={lat:20,lon:60,d:3.4};function w(){let e=(0,l.useMemo)(()=>{let e=new Float32Array(7500),t=7,a=()=>(t=16807*t%0x7fffffff)/0x7fffffff;for(let t=0;t<2500;t++){let r=2*a()-1,o=2*a()*Math.PI,n=Math.sqrt(1-r*r),l=60+30*a();e.set([l*n*Math.cos(o),l*r,l*n*Math.sin(o)],3*t)}let r=new i.LoY;return r.setAttribute("position",new i.THS(e,3)),r},[]),t=(0,l.useRef)(null);return(0,o.F)(()=>{t.current&&(t.current.opacity=.7*(1-(f.zZ.get("morph")?.[0]??0)))}),(0,r.jsx)("points",{geometry:e,children:(0,r.jsx)("pointsMaterial",{ref:t,size:1.2,sizeAttenuation:!1,color:"#c8d3e6",transparent:!0,opacity:.7,depthWrite:!1})})}function y({lowDetail:e}){let t="/projects/pulse-economic-activity/demo",{main:a,strip:n,geo:u,stripGeo:c}=(0,l.useMemo)(()=>{let a=new i.Tap().load(`${t}/textures/earth-day-${e?"1k":"2k"}.jpg`);return a.colorSpace=i.er$,a.wrapS=i.GJx,a.anisotropy=4,{main:v(a,0),strip:v(a,360),geo:new i.bdM(1,1,e?128:256,e?64:128),stripGeo:new i.bdM(1,1,64,128)}},[t,e]);return(0,l.useMemo)(()=>{let e=c.getAttribute("uv");for(let t=0;t<e.count;t++)e.setX(t,.25*e.getX(t))},[c]),(0,o.F)(()=>{let e=f.zZ.get("morph")?.[0]??0,t=.3*!!["port","region"].includes((0,s.Jt)().view);for(let r of[a,n])r.uniforms.uMorph.value=e,r.uniforms.uDim.value=t}),(0,r.jsxs)(r.Fragment,{children:[(0,r.jsx)("mesh",{geometry:u,material:a,frustumCulled:!1}),(0,r.jsx)("mesh",{geometry:c,material:n,frustumCulled:!1,renderOrder:-1})]})}function x(e){let t=(0,s.Jt)(),a=Math.max(0,Math.min(t.window.end,Math.floor(f.pm.t)));for(let r of e)u.Ci.forEach((e,o)=>{let n=u.hz.find(t=>t.id===e.from),l=u.hz.find(t=>t.id===e.to),i=u.gi.find(t=>t.key===e.commodity);r.uniforms.uLanes.value[o].set(n.lat,n.lon,l.lat,l.lon),r.uniforms.uColor.value[o].set(i.colour);let s=(t.derived?.lane30[o][a]??0)/30;r.uniforms.uWidth.value[o]=.0015+9e-4*Math.sqrt(s),r.uniforms.uMask.value[o]="all"===t.commodity||t.commodity===e.commodity?1:.07})}function M(){let e=(0,s.nm)(e=>e.bundle?.voyages??null),t=(0,s.nm)(e=>e.stress),{gl:a,size:n}=(0,o.D)(),c=(0,l.useMemo)(()=>new i.BKk({transparent:!0,depthWrite:!1,blending:i.EZo,side:i.$EB,uniforms:{uMorph:{value:0},uLanes:{value:Array(64).fill(0).map(()=>new i.IUQ)},uWidth:{value:Array(64).fill(0)},uMask:{value:Array(64).fill(1)},uColor:{value:Array(64).fill(0).map(()=>new i.Q1f)}},vertexShader:`
      ${m}
      ${d}
      attribute float aLane; attribute float aT; attribute float aSide;
      varying float vAlpha; varying vec3 vColor; varying float vEdge;
      void main() {
        int i = int(aLane + 0.5);
        vec4 lane = uLanes[i];
        vec3 p = arcPoint(lane, aT) + sideAt(lane, aT) * aSide * 0.5 * uWidth[i];
        vAlpha = 0.13 * uMask[i]; vColor = uColor[i]; vEdge = aSide;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,fragmentShader:`
      varying float vAlpha; varying vec3 vColor; varying float vEdge;
      void main() { gl_FragColor = vec4(vColor, vAlpha * (1.0 - abs(vEdge) * 0.7)); }`}),[]),v=(0,l.useMemo)(()=>new i.BKk({transparent:!0,depthWrite:!1,blending:i.EZo,uniforms:{uMorph:{value:0},uT:{value:0},uScale:{value:1},uLanes:{value:Array(64).fill(0).map(()=>new i.IUQ)},uWidth:{value:Array(64).fill(0)},uMask:{value:Array(64).fill(1)},uColor:{value:Array(64).fill(0).map(()=>new i.Q1f)}},vertexShader:`
      ${m}
      ${d}
      uniform float uT; uniform float uScale;
      attribute float aLane; attribute float aDep; attribute float aArr; attribute float aCargo; attribute float aSeed;
      varying vec3 vColor; varying float vAlpha;
      void main() {
        float f = (uT - aDep) / max(1e-3, aArr - aDep);
        int i = int(aLane + 0.5);
        if (f < 0.0 || f > 1.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); gl_PointSize = 0.0; return; } // not at sea on this day
        vec4 lane = uLanes[i];
        vec3 p = arcPoint(lane, f) + sideAt(lane, f) * (aSeed - 0.5) * 0.8 * uWidth[i];
        vColor = uColor[i]; vAlpha = uMask[i];
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = (1.6 + 3.2 * sqrt(aCargo / 270.0)) * uScale;
      }`,fragmentShader:`
      varying vec3 vColor; varying float vAlpha;
      void main() { float r = length(gl_PointCoord - 0.5); if (r > 0.5) discard; gl_FragColor = vec4(vColor, vAlpha * smoothstep(0.5, 0.0, r)); }`}),[]),p=(0,l.useMemo)(()=>{let e=[],t=[],a=[],r=[];u.Ci.forEach((o,n)=>{let l=e.length;for(let r=0;r<=64;r++)for(let o of[-1,1])e.push(n),t.push(r/64),a.push(o);for(let e=0;e<64;e++){let t=l+2*e;r.push(t,t+1,t+2,t+1,t+3,t+2)}});let o=new i.LoY;return o.setAttribute("position",new i.THS(new Float32Array(3*e.length),3)),o.setAttribute("aLane",new i.qtW(e,1)),o.setAttribute("aT",new i.qtW(t,1)),o.setAttribute("aSide",new i.qtW(a,1)),o.setIndex(r),o},[]),h=(0,l.useMemo)(()=>{if(!e)return null;let a=t?10:1,r=e.length*a,o=new Float32Array(r),n=new Float32Array(r),l=new Float32Array(r),u=new Float32Array(r),s=new Float32Array(r),f=1,c=()=>(f=16807*f%0x7fffffff)/0x7fffffff;for(let t=0;t<a;t++)e.forEach((a,r)=>{let i=t*e.length+r,f=t?(c()-.5)*20:0;o[i]=a[0],n[i]=a[3]+f,l[i]=a[4]+f,u[i]=a[6],s[i]=c()});let m=new i.LoY;for(let[e,t]of(m.setAttribute("position",new i.THS(new Float32Array(3*r),3)),Object.entries({aLane:o,aDep:n,aArr:l,aCargo:u,aSeed:s})))m.setAttribute(e,new i.THS(t,1));return m.boundingSphere=new i.iyt(new i.Pq0,100),m},[e,t]),g=(0,l.useRef)(0);return(0,o.F)((e,t)=>{let r=f.zZ.get("morph")?.[0]??0;c.uniforms.uMorph.value=r,v.uniforms.uMorph.value=r,v.uniforms.uT.value=f.pm.t,v.uniforms.uScale.value=Math.min(2,a.getPixelRatio())*(n.width<700?.8:1),g.current+=t,g.current>.2&&(g.current=0,x([c,v]))}),(0,l.useEffect)(()=>{x([c,v])},[c,v,e]),(0,r.jsxs)(r.Fragment,{children:[(0,r.jsx)("mesh",{geometry:p,material:c,frustumCulled:!1}),h?(0,r.jsx)("points",{geometry:h,material:v,frustumCulled:!1}):null]})}function z(){let e=(0,s.nm)(e=>e.derived),t=(0,s.nm)(e=>e.port),{gl:a,camera:n,size:d}=(0,o.D)(),v=(0,l.useMemo)(()=>new i.BKk({transparent:!0,depthWrite:!1,uniforms:{uMorph:{value:0},uScale:{value:1},uWall:{value:0},uReduced:{value:0},uSelected:{value:-1},uSize:{value:Array(40).fill(0)},uZ:{value:Array(40).fill(0)}},vertexShader:`
      ${m}
      uniform float uScale; uniform float uSize[40]; uniform float uZ[40]; uniform float uSelected;
      attribute float aIdx; attribute float aLat; attribute float aLon;
      varying float vZ; varying float vSel;
      void main() {
        int i = int(aIdx + 0.5);
        vec3 p = projectP(aLat, aLon, 0.006);
        vZ = uZ[i]; vSel = abs(aIdx - uSelected) < 0.5 ? 1.0 : 0.0;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = (8.0 + 18.0 * uSize[i]) * uScale;
      }`,fragmentShader:`
      uniform float uWall; uniform float uReduced;
      varying float vZ; varying float vSel;
      void main() {
        float r = length(gl_PointCoord - 0.5);
        if (r > 0.5) discard;
        float level = clamp((vZ - 2.0) / 6.0, 0.0, 1.0);
        vec3 col = vZ >= 4.0 ? vec3(1.0, 0.42, 0.35) : vZ >= 2.0 ? vec3(1.0, 0.75, 0.33) : vec3(0.85, 0.92, 1.0);
        float core = smoothstep(0.16, 0.1, r);
        // congestion: a slow pulse (under 1 Hz, faster when worse); reduced motion shows a static ring whose width carries the level
        float ringW = uReduced > 0.5 ? 0.04 + 0.1 * level : 0.05;
        float phase = uReduced > 0.5 || vZ < 2.0 ? 1.0 : 0.5 + 0.5 * sin(6.2832 * (0.25 + 0.35 * level) * uWall);
        float ringR = uReduced > 0.5 || vZ < 2.0 ? 0.38 : 0.22 + 0.24 * (1.0 - phase);
        float ring = smoothstep(ringW, 0.0, abs(r - ringR)) * (vZ >= 2.0 ? 0.5 + 0.5 * phase : 0.35);
        float sel = vSel * smoothstep(0.03, 0.0, abs(r - 0.47));
        gl_FragColor = vec4(mix(col, vec3(1.0), sel), max(core, max(ring, sel)));
      }`}),[]),p=(0,l.useMemo)(()=>{let e=new i.LoY;return e.setAttribute("position",new i.THS(new Float32Array(3*u.hz.length),3)),e.setAttribute("aIdx",new i.qtW(u.hz.map((e,t)=>t),1)),e.setAttribute("aLat",new i.qtW(u.hz.map(e=>e.lat),1)),e.setAttribute("aLon",new i.qtW(u.hz.map(e=>e.lon),1)),e},[]);return(0,l.useEffect)(()=>{v.uniforms.uSelected.value=t?u.hz.findIndex(e=>e.id===t):-1},[t,v]),(0,l.useEffect)(()=>{let e=a.domElement,t=null,r=e=>{t=[e.clientX,e.clientY]},o=a=>{if(!t||Math.hypot(a.clientX-t[0],a.clientY-t[1])>4||(0,c.zF)((0,s.Jt)().view))return;let r=e.getBoundingClientRect(),o=f.zZ.get("morph")?.[0]??0,l=[16,null],m=n.position.clone().normalize();for(let e of u.hz){let t=new i.Pq0(...(0,u.Cv)(e.lat,e.lon,.006,o));if(o<.5&&.1>t.clone().normalize().dot(m))continue;t.project(n);let s=Math.hypot((.5*t.x+.5)*r.width-(a.clientX-r.left),(-(.5*t.y)+.5)*r.height-(a.clientY-r.top));s<l[0]&&(l=[s,e.id])}l[1]&&(0,s.wU)(l[1])};return e.addEventListener("pointerdown",r),e.addEventListener("pointerup",o),()=>{e.removeEventListener("pointerdown",r),e.removeEventListener("pointerup",o)}},[a,n]),(0,o.F)(t=>{let r=(0,s.Jt)(),o=Math.max(0,Math.min(r.window.end,Math.floor(f.pm.t)));v.uniforms.uMorph.value=f.zZ.get("morph")?.[0]??0,v.uniforms.uWall.value=r.motionPaused?0:t.clock.elapsedTime,v.uniforms.uReduced.value=+!!r.reduced,v.uniforms.uScale.value=Math.min(2,a.getPixelRatio())*(d.width<700?.8:1),e&&u.hz.forEach((t,a)=>{let r=e.ports[t.id].arrivals,n=0;for(let e=Math.max(0,o-29);e<=o;e++)n+=r[e];v.uniforms.uSize.value[a]=Math.min(1,Math.sqrt(n/30/12));let l=e.ports[t.id].z[o];v.uniforms.uZ.value[a]=Number.isFinite(l)?l:0})}),(0,r.jsx)("points",{geometry:p,material:v,frustumCulled:!1})}function b(){let{camera:e,gl:t}=(0,o.D)(),a=(0,l.useRef)("");return(0,l.useEffect)(()=>{let e=t.domElement,a=null,r=e=>{a=[e.clientX,e.clientY]},o=e=>{if(!a||(0,c.zF)((0,s.Jt)().view))return;let t=e.clientX-a[0],r=e.clientY-a[1];a=[e.clientX,e.clientY];let o="flat"===(0,s.Jt)().mapMode?.12*g.d:.25*g.d;g.lon-=t*o,g.lat=Math.max(-75,Math.min(80,g.lat+r*o*("flat"===(0,s.Jt)().mapMode?-1:1))),f.zZ.set("cam",h(g.lat,g.lon,g.d,f.zZ.get("morph")?.[0]??0))},n=()=>{a=null},l=e=>{(0,c.zF)((0,s.Jt)().view)||(e.preventDefault(),g.d=Math.max("flat"===(0,s.Jt)().mapMode?.4:1.15,Math.min(6,g.d*Math.exp(.001*e.deltaY))),f.zZ.set("cam",h(g.lat,g.lon,g.d,f.zZ.get("morph")?.[0]??0)))};return e.addEventListener("pointerdown",r),window.addEventListener("pointermove",o),window.addEventListener("pointerup",n),e.addEventListener("wheel",l,{passive:!1}),()=>{e.removeEventListener("pointerdown",r),window.removeEventListener("pointermove",o),window.removeEventListener("pointerup",n),e.removeEventListener("wheel",l)}},[t]),(0,o.F)((t,r)=>{let o=(0,s.Jt)();f.zZ.policy.reduced=o.reduced,f.zZ.policy.paused=o.motionPaused,(0,f.np)(1e3*r,performance.now()),f.zZ.tick(Math.min(100,1e3*r)),f.Y9.frame(performance.now());let n=`${o.view}|${o.mapMode}|${o.region}|${o.port}`;if(n!==a.current){let e=function(e){let t=(0,s.Jt)(),a=+("flat"===t.mapMode),r=t.bundle?.regions.find(e=>e.id===t.region),o=t.bundle?.ports.find(e=>e.id===t.port);switch(e){case"intro0":return{lat:22,lon:70,d:3.9,morph:0};case"intro1":return{lat:24,lon:78,d:2.9,morph:0};case"intro2":return{lat:30,lon:123,d:2,morph:0};case"intro3":return{lat:20,lon:75,d:3.6,morph:1};case"region":return r?{lat:r.lat,lon:r.lon,d:a?1.8:2.1,morph:a}:{...g,morph:a};case"port":return o?{lat:o.lat,lon:o.lon,d:a?1:1.5,morph:a}:{...g,morph:a};default:return{lat:18,lon:60,d:a?4.2:3.4,morph:a}}}(o.view);Object.assign(g,{lat:e.lat,lon:e.lon,d:e.d}),f.zZ.get("morph")||f.zZ.set("morph",[e.morph]),f.zZ.to("morph",[e.morph],1400),f.zZ.get("cam")?f.zZ.to("cam",h(e.lat,e.lon,e.d,e.morph),1400):f.zZ.set("cam",h(e.lat,e.lon,e.d,e.morph)),a.current=n}f.zZ.busy("morph")&&!f.zZ.busy("cam")&&f.zZ.set("cam",h(g.lat,g.lon,g.d,f.zZ.get("morph")[0]));let l=f.zZ.get("cam");e.position.set(l[0],l[1],l[2]),e.up.set(0,1,0),e.lookAt(l[3],l[4],l[5])}),null}function A(){let{gl:e}=(0,o.D)();return(0,l.useEffect)(()=>{requestAnimationFrame(()=>f.Y9.mark("sceneLoadMs",performance.now()));let t=e.domElement,a=e=>{e.preventDefault(),f.Y9.contextLost(),(0,s.hZ)({webgl:"lost"})},r=()=>(0,s.hZ)({webgl:"ok"});t.addEventListener("webglcontextlost",a),t.addEventListener("webglcontextrestored",r);let o=setInterval(()=>{let t=e.info,a=(0,s.Jt)();f.Y9.sample({calls:t.render.calls,triangles:t.render.triangles,points:t.render.points,geometries:t.memory.geometries,textures:t.memory.textures,programs:t.programs?.length??0},(a.bundle?.voyages.length??0)*(a.stress?10:1))},500),n=setInterval(()=>f.Y9.flush(),3e4);return()=>{clearInterval(o),clearInterval(n),t.removeEventListener("webglcontextlost",a),t.removeEventListener("webglcontextrestored",r)}},[e]),null}let S=u.cG.port;function E(){let e=window.innerWidth<700||(navigator.hardwareConcurrency??8)<=4;return(0,r.jsxs)(n.Hl,{className:"globe","aria-hidden":!0,dpr:[1,e?1.5:2],gl:{antialias:!e,powerPreference:"high-performance",preserveDrawingBuffer:!0},camera:{fov:40,near:.01,far:500,position:[0,0,4]},onCreated:({gl:e,scene:t,camera:a})=>{e.setClearColor("#03050a");let r=performance.now();e.compile(t,a),f.Y9.mark("shaderCompileMs",performance.now()-r)},children:[(0,r.jsx)(A,{}),(0,r.jsx)(w,{}),(0,r.jsx)(y,{lowDetail:e}),(0,r.jsx)(M,{}),(0,r.jsx)(z,{}),(0,r.jsx)(b,{})]})}}}]);