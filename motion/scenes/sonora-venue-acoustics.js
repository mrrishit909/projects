/* Does the Back of the Hall Hear the Same Concert as the Front? Left: definition D50 in the chamber-music preset, percent (front stalls 42, balcony 20).
   Right: mid RT60 1.61 s, with foam on the rear wall 1.22 s; rear stalls C80 -4.4 to -3.4 dB; 1,063 seats. Every figure is on the project page. */
scene({
  slug: "sonora-venue-acoustics", aspect: 1.72, seconds: 6, bg: ["#1a0e12", "#070708"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DEFINITION D50, PERCENT",
    bars: [["Front stalls", 42, "42", "#F1A341"], ["Balcony", 20, "20", "#3A80BF"]],
    stats: [["Mid RT60 with plaster rear wall", "1.61 s", "#F5E8D2"], ["With foam on the rear wall", "1.22 s", "#F1A341"], ["Rear stalls C80", "-4.4 to -3.4 dB", "#C59A49"], ["Seats in the hall", "1,063", "#F5E8D2"]],
  }),
});
