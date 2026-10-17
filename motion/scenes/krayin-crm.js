/* Keystone (inspired by Krayin): Every lead to the right rep, and every record visible to exactly the right people.
   Right: counts from the fresh-clone gate (docs/evidence/krayin/VERIFICATION.md at commit 9522ef029e): Unit tests 2; Integration tests 31; Browser tests 15; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "krayin-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#87b5ae", ACC2 = "#e1a086";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "KEYSTONE  ROUTING AND VISIBILITY", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const lanes=3,cy=(y0+y1)/2;for(let l=0;l<lanes;l++){const y=y0+(y1-y0)*(l+0.5)/lanes;line(g,x0+(x1-x0)*0.35,y,x1,y,hex(ink,0.15),2);txt(g,['OWNER','MANAGER','AGENT'][l],x1,y-H*0.02,{size:H*0.018,color:hex(ink,0.5),align:'right',spacing:2});}for(let i=0;i<7;i++){const p=ease.inOut(seg(u,0.05+i*0.1,0.45+i*0.1)),l=i%lanes,yl=y0+(y1-y0)*(l+0.5)/lanes,x=lerp(x0,x1-H*0.05,p),y=lerp(cy,yl,seg(p,0.35,0.7));dot(g,x,y,H*0.013,l===1?ACC2:ACC);}
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","2"],["Integration tests","31"],["Browser tests","15"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
