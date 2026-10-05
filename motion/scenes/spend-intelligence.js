/* Where Is the Money Leaking Out of Accounts Payable? Left: duplicate payments found in a year (This build 195; The usual check 50).
   Right: Paid twice $3.03M; Billed above contract rate $1.80M; Rebate earned, not credited $1.40M; Leakage found $6.2M. Every figure is on the project page. */
scene({
  slug: "spend-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DUPLICATE PAYMENTS FOUND IN A YEAR",
    bars: [["This build", 195, "195"], ["The usual check", 50, "50"]],
    stats: [["Paid twice", "$3.03M", "#ff8a3d"], ["Billed above contract rate", "$1.80M", "#ff8a3d"], ["Rebate earned, not credited", "$1.40M", "#ff8a3d"], ["Leakage found", "$6.2M", "#4a95f0"]],
  }),
});
