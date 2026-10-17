/* Dovecote (inspired by iDURAR): A small support desk where the client sees the answer, and only the answer.
   Right: counts from the fresh-clone gate (docs/evidence/idurar/VERIFICATION.md at commit bf0b91ff8a): Unit tests 2; Integration tests 39; Browser tests 22; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "idurar-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#ee6c4d", ACC2 = "#3d8bb5";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "DOVECOTE  SUPPORT DESK AND PORTAL", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const cols=3,cw=(x1-x0)/cols;for(let c=0;c<cols;c++){const x=x0+c*cw;txt(g,['OPEN','IN PROGRESS','RESOLVED'][c],x+cw/2,y0-H*0.02,{size:H*0.018,color:hex(ink,0.5),align:'center',spacing:2});rr(g,x+cw*0.05,y0,cw*0.9,y1-y0,H*0.012);g.fillStyle=hex(ink,0.05);g.fill();}for(let i=0;i<3;i++){const p=ease.inOut(seg(u,0.1+i*0.2,0.45+i*0.2)),x=lerp(x0+cw*0.1,x0+cw*2.1,p*(i===2?1:0.5)),y=y0+H*0.04+i*H*0.1;rr(g,x,y,cw*0.8,H*0.07,H*0.008);g.fillStyle=i===0?ACC:hex(ink,0.18);g.fill();}g.beginPath();g.arc(x1-H*0.05,y1+H*0.05,H*0.03,-Math.PI/2,-Math.PI/2+Math.PI*2*seg(u,0.1,0.9));g.strokeStyle=ACC2;g.lineWidth=4;g.stroke();
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","2"],["Integration tests","39"],["Browser tests","22"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
