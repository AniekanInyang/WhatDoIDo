export const conversationMessages = [
  { role: "assistant", text: "What is the core decision you need to make today?" },
  { role: "user", text: "I need to choose between a startup offer and my current role." },
  {
    role: "assistant",
    text: "What constraints matter most right now: income stability, learning speed, or location flexibility?",
  },
  { role: "user", text: "Income stability and long-term growth are both critical." },
];

export const historyItems = [
  { id: "D-1024", title: "Career move: startup vs enterprise", confidence: 0.78, date: "2026-07-10" },
  { id: "D-1022", title: "Relocation decision for new role", confidence: 0.71, date: "2026-07-08" },
  { id: "D-1016", title: "Graduate school timing", confidence: 0.83, date: "2026-07-05" },
];

export const insightStats = [
  { label: "Decisions completed", value: "32" },
  { label: "Average confidence", value: "0.76" },
  { label: "Clarification turns", value: "4.2" },
  { label: "Reversals after 30d", value: "9%" },
];
