/* Meridian (inspired by SuiteCRM): Reports you can trust, imports that say what went wrong, and automations that run once even when a worker dies.
   Right: counts from the fresh-clone gate (docs/evidence/suitecrm/VERIFICATION.md at commit 0c920163e6): Unit tests 7; Integration tests 49; Browser tests 18; Worst list p95, 100,000 contacts 78.4 ms. */
scene({
  slug: "suitecrm-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#4da3ff", ACC2 = "#ffb454";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "MERIDIAN  REPORTS, WORKFLOWS, SCALE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const bars=[0.9,0.62,0.45,0.3,0.2],bw=(x1-x0)*0.5/bars.length;bars.forEach((v,i)=>{const h=(y1-y0)*v*ease.out5(seg(u,0.05+i*0.06,0.3+i*0.06));rr(g,x0+i*bw*1.15,y1-h,bw,h,H*0.006);g.fillStyle=i===0?ACC:hex(ink,0.25);g.fill();});const qx=x0+(x1-x0)*0.62;for(let i=0;i<8;i++){const p=((u*2+i/8)%1),x=lerp(qx,x1,p),y=y0+(y1-y0)*(0.2+0.6*(i%3)/2);dot(g,x,y,H*0.012,p>0.7?ACC2:hex(ink,0.5));}txt(g,'outbox  ->  worker',qx,y0-H*0.02,{size:H*0.02,color:hex(ink,0.5),spacing:2});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","7"],["Integration tests","49"],["Browser tests","18"],["Worst list p95, 100,000 contacts","78.4 ms"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
