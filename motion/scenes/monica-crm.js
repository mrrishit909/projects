/* Kin (inspired by Monica): Remember the people who matter, and keep what you write about them private.
   Right: counts from the fresh-clone gate (docs/evidence/monica/VERIFICATION.md at commit 55ab57c54c): Unit tests 7; Integration tests 29; Browser tests 18; Gate, fresh clone 20 pass, 0 fail. */
scene({
  slug: "monica-crm", aspect: 1.72, seconds: 6, bg: ["#13161a","#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ACC = "#daa995", ACC2 = "#6f8f72";
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.78;
    txt(g, "KIN  PRIVACY AND REMINDERS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5 });
    const cx=(x0+x1)/2,cy=(y0+y1)/2,R=(y1-y0)*0.38;dot(g,cx,cy,H*0.04,ACC,ACC);for(let i=0;i<9;i++){const an=i/9*Math.PI*2+u*0.4,r=R*(i%2?0.75:1),x=cx+Math.cos(an)*r,y=cy+Math.sin(an)*r*0.8;line(g,cx,cy,x,y,hex(ink,0.18),1.5);dot(g,x,y,H*0.016,i===3?ACC2:hex(ink,0.5));}const pr=seg(u,0.5,0.9);g.beginPath();g.arc(cx,cy,H*0.04+pr*R,0,Math.PI*2);g.strokeStyle=hex(ACC2,0.6*(1-pr));g.lineWidth=3;g.stroke();
    const rx = W * 0.64, rw = W * 0.29;
    txt(g, "GATE, FRESH CLONE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Unit tests","7"],["Integration tests","29"],["Browser tests","18"],["Gate, fresh clone","20 pass, 0 fail"]].forEach(([nm, val], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, val, rx + rw, y + H * 0.05, { size: H * 0.04, color: i === 3 ? ACC2 : ACC, align: 'right', alpha: t });
    });
  },
});
