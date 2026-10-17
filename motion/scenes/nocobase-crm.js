/* Loom (inspired by NocoBase): Define your own data model in the browser and use it a second later.
   Right: counts from the fresh-clone gate (docs/evidence/nocobase/VERIFICATION.md at commit 19ed093e9a): Unit tests 2; Integration tests 35; Browser tests 14; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "nocobase-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#9d7cff", ACC2 = "#3ddc97";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "LOOM  DATA-MODEL BUILDER", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const rows=6,cols=4,cw=(x1-x0)/cols;for(let c=0;c<cols;c++){const on=seg(u,0.05+c*0.12,0.2+c*0.12);rr(g,x0+c*cw+4,y0,cw-8,H*0.05,H*0.008);g.fillStyle=hex(c===3?ACC:ink,c===3?0.9:0.18*on);g.fill();for(let r=0;r<rows;r++){const f=seg(u,0.45+r*0.06,0.6+r*0.06);rr(g,x0+c*cw+4,y0+H*0.08+r*H*0.075,(cw-8)*f,H*0.045,H*0.006);g.fillStyle=hex(ink,0.1);g.fill();}}txt(g,'a new field, used at once',x0,y1+H*0.03,{size:H*0.02,color:hex(ink,0.5)});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","2"],["Integration tests","35"],["Browser tests","14"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
