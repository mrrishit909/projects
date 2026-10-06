/* Who Gets Paid for This Play? Left: usage lines matched to a recording, one quarter (Exact ISRC only 54%; With identity resolution 98% precision).
   Right: Overlapping claim: money moved to hold $534; Clip match at 20 dB vs 10 dB noise 93–97% vs 23–33%; Royalty entries balance the pools to the cent; Duplicate lines caught 40. Every figure is on the project page. */
scene({
  slug: "music-rights-ledger", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "USAGE LINES MATCHED TO A RECORDING, ONE QUARTER",
    bars: [["Exact ISRC only", 54, "54%"], ["With identity resolution", 98, "98% precision", "#8a8f98"]],
    stats: [["Overlapping claim: money moved to hold", "$534", "#ff8a3d"], ["Clip match at 20 dB vs 10 dB noise", "93–97% vs 23–33%", "#ff8a3d"], ["Royalty entries balance the pools", "to the cent", "#8a8f98"], ["Duplicate lines caught", "40", "#4a95f0"]],
  }),
});
