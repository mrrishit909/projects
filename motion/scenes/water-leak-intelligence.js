/* Is It a Leak, a Bad Sensor, or Just a Busy Night? Left: leaks located within 180 metres (Fitting the pressure pattern 84%; Sensor that dropped most 29%).
   Right: False leak alarms 0 of 450; Leaks found 129 of 129; Demo leak, distance off 60 m; Cost avoided $4.9M vs $2.2M. Every figure is on the project page. */
scene({
  slug: "water-leak-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "LEAKS LOCATED WITHIN 180 METRES",
    bars: [["Fitting the pressure pattern", 84, "84%"], ["Sensor that dropped most", 29, "29%"]],
    stats: [["False leak alarms", "0 of 450", "#4a95f0"], ["Leaks found", "129 of 129", "#4a95f0"], ["Demo leak, distance off", "60 m", "#4a95f0"], ["Cost avoided", "$4.9M vs $2.2M", "#4a95f0"]],
  }),
});
