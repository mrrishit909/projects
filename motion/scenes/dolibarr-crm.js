/* Rackhouse (inspired by Dolibarr): A business system you assemble from modules, where switching one off really means off.
   Right: counts from the fresh-clone gate (docs/evidence/dolibarr/VERIFICATION.md at commit 9577fdc7a3): Unit tests 2; Integration tests 34; Browser tests 15; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "dolibarr-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#d4572a", ACC2 = "#95b7cb";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "RACKHOUSE  MODULE SYSTEM", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const n=4,rh=(y1-y0)/n;['CONTACTS','INVENTORY','SALES','INVOICING'].forEach((s,i)=>{const y=y0+i*rh,on=i===0||i===2?1:i===1?seg(u,0.3,0.4):seg(u,0.55,0.65)*(1-seg(u,0.8,0.9));rr(g,x0,y+rh*0.1,x1-x0,rh*0.8,H*0.01);g.fillStyle=hex(ink,0.06);g.fill();txt(g,s,x0+H*0.03,y+rh*0.58,{size:H*0.024,color:hex(ink,0.8),spacing:2});rr(g,x1-H*0.12,y+rh*0.3,H*0.09,rh*0.4,rh*0.2);g.fillStyle=on>0.5?ACC:hex(ink,0.2);g.fill();dot(g,x1-H*0.12+rh*0.2+(on>0.5?H*0.09-rh*0.4:0),y+rh*0.5,rh*0.15,'#fff');});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","2"],["Integration tests","34"],["Browser tests","15"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
