/* Ledgerleaf (inspired by Akaunting): Invoice a client, record what actually arrived, and see the difference.
   Right: counts from the fresh-clone gate (docs/evidence/akaunting/VERIFICATION.md at commit 158bf70109): Unit tests 7; Integration tests 39; Browser tests 16; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "akaunting-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#8fb7aa", ACC2 = "#b8872e";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "LEDGERLEAF  INVOICES AND PAYMENTS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const n=5;for(let i=0;i<n;i++){const on=ease.out5(seg(u,0.05+i*0.1,0.2+i*0.1)),y=y0+i*H*0.09;line(g,x0,y,x1,y,hex(ink,0.12),1);txt(g,'item '+(i+1),x0,y-H*0.012,{size:H*0.022,color:hex(ink,0.7),alpha:on});txt(g,['120.00','49.99','310.25','18.40','75.10'][i],x1,y-H*0.012,{size:H*0.022,color:hex(ink,0.85),align:'right',alpha:on});}const tt=seg(u,0.65,0.8);txt(g,'TOTAL  573.74',x1,y1,{size:H*0.045,color:ACC,align:'right',alpha:tt});txt(g,'received  400.00  ->  open  173.74',x1,y1+H*0.06,{size:H*0.022,color:ACC2,align:'right',alpha:seg(u,0.8,0.92)});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","7"],["Integration tests","39"],["Browser tests","16"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
