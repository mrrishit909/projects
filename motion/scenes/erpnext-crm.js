/* Fennel Distribution (inspired by ERPNext): From a won deal to a balanced ledger, with every step posting exactly once.
   Right: counts from the fresh-clone gate (docs/evidence/erpnext/VERIFICATION.md at commit 55ab57c54c): Unit tests 10; Integration tests 59; Browser tests 17; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "erpnext-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#7ad9a8", ACC2 = "#f2c35b";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "FENNEL DISTRIBUTION  DOUBLE-ENTRY LEDGER", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const n=5,xs=(i)=>x0+(x1-x0)*i/(n-1),ym=(y0+y1)/2;line(g,xs(0),ym,xs(n-1),ym,hex(ink,0.15),2);['QUOTE','ORDER','DELIVERY','INVOICE','PAYMENT'].forEach((s,i)=>{const on=seg(u,0.1+i*0.15,0.2+i*0.15);dot(g,xs(i),ym,H*0.03,on>0.5?ACC:hex(ink,0.2),on>0.5?ACC:null);txt(g,s,xs(i),ym+H*0.09,{size:H*0.018,color:hex(ink,0.6),align:'center',spacing:1});});const p=ease.inOut(seg(u,0.1,0.85));dot(g,lerp(xs(0),xs(n-1),p),ym,H*0.012,'#fff','#fff');const bal=seg(u,0.8,0.95);txt(g,'DEBIT = CREDIT',(x0+x1)/2,y1,{size:H*0.03,color:ACC2,align:'center',alpha:bal,spacing:3});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","10"],["Integration tests","59"],["Browser tests","17"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
