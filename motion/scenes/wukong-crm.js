/* Canopy (inspired by WuKong CRM): An org chart that decides who sees which lead, and campaigns that stop when someone says stop.
   Right: counts from the fresh-clone gate (docs/evidence/wukong/VERIFICATION.md at commit 4d3e8b38f7): Unit tests 7; Integration tests 35; Browser tests 16; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "wukong-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#f2b705", ACC2 = "#4cc9a7";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "CANOPY  ORG CHART AND CAMPAIGNS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const nodes=[[0.5,0.08],[0.25,0.35],[0.75,0.35],[0.12,0.65],[0.38,0.65],[0.62,0.65],[0.88,0.65]],ed=[[0,1],[0,2],[1,3],[1,4],[2,5],[2,6]];const P=(i)=>[x0+(x1-x0)*nodes[i][0],y0+(y1-y0)*nodes[i][1]];ed.forEach(([p,q],k)=>{const f=seg(u,0.05+k*0.07,0.2+k*0.07),A=P(p),B=P(q);line(g,A[0],A[1],lerp(A[0],B[0],f),lerp(A[1],B[1],f),hex(ink,0.25),2);});nodes.forEach((_,i)=>{const [x,y]=P(i),hid=i===2||i>=5,on=seg(u,0.5,0.7);dot(g,x,y,H*0.025,hid&&on>0.5?hex(ink,0.15):ACC,hid&&on>0.5?null:ACC);});txt(g,'a restricted branch is hidden from above',(x0+x1)/2,y1+H*0.05,{size:H*0.02,color:hex(ink,0.5),align:'center'});
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","7"],["Integration tests","35"],["Browser tests","16"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
