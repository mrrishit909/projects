/* Kestrel CRM (inspired by Twenty): A CRM that stays out of your way: fast tables, a command palette, an API for everything.
   Right: counts from the fresh-clone gate (docs/evidence/twenty/VERIFICATION.md at commit 55ab57c54c): Unit tests 9; Integration tests 59; Browser tests 19; Worst concurrent p95, 10,000 contacts 14.8 ms. */
scene({
  slug: "twenty-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#97adff", ACC2 = "#8a8f98";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "KESTREL CRM  API AND WEBHOOKS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const cols=4,cw=(x1-x0)/cols;for(let c=0;c<cols;c++){const x=x0+c*cw;txt(g,['LEAD','QUALIFIED','PROPOSAL','WON'][c],x+cw/2,y0-H*0.02,{size:H*0.02,color:hex(ink,0.5),align:'center',spacing:2});rr(g,x+cw*0.06,y0,cw*0.88,y1-y0,H*0.012);g.fillStyle=hex(ink,0.05);g.fill();for(let k=0;k<3-(c>1?1:0);k++){rr(g,x+cw*0.12,y0+H*0.03+k*H*0.1,cw*0.76,H*0.07,H*0.008);g.fillStyle=hex(ink,0.12);g.fill();}}const p=ease.inOut(seg(u,0.15,0.75)),cx=lerp(x0+cw*0.12,x0+cw*3.12,p),cy=lerp(y0+H*0.03,y0+H*0.03+H*0.1*2,Math.sin(p*Math.PI)*0.6+p*0.4);rr(g,cx,cy,cw*0.76,H*0.07,H*0.008);g.fillStyle=ACC;g.fill();
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","9"],["Integration tests","59"],["Browser tests","19"],["Worst concurrent p95, 10,000 contacts","14.8 ms"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
