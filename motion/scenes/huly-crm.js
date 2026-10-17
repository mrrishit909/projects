/* Hearth (inspired by Huly): A small studio's rooms, boards and shared documents, live.
   Right: counts from the fresh-clone gate (docs/evidence/huly/VERIFICATION.md at commit 2a04b27058): Unit tests 2; Integration tests 32; Browser tests 19; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "huly-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#ff8a3d", ACC2 = "#5fb3c9";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "HEARTH  REALTIME COLLABORATION", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    for(let i=0;i<9;i++){const w=(0.4+0.5*((i*37)%7)/7)*(x1-x0),on=seg(u,0.1+i*0.05,0.5+i*0.05);rr(g,x0,y0+i*H*0.07,w*on,H*0.03,H*0.01);g.fillStyle=hex(ink,0.16);g.fill();}const a1=seg(u,0.2,0.8);dot(g,x0+(x1-x0)*(0.2+0.5*a1),y0+H*0.07*3+H*0.015,H*0.012,ACC,ACC);dot(g,x0+(x1-x0)*(0.7-0.4*a1),y0+H*0.07*6+H*0.015,H*0.012,ACC2,ACC2);txt(g,'two people, one document',x0,y1+H*0.09,{size:H*0.02,color:hex(ink,0.5)});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","2"],["Integration tests","32"],["Browser tests","19"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
