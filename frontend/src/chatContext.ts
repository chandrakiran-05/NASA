/** The existing ask endpoint accepts one question, not a server-side chat session. */
export function conversationQuestion(question: string, previousTurns: string[]): string {
  const current = question.trim();
  if (!current || current.length > 2000) throw new Error("Enter a question of 1 to 2,000 characters.");
  const prefix = "Earlier Earth-science conversation (context only, not new observations):\n";
  const suffix = "\n\nAnswer this latest question: ";
  const budget = 2000 - current.length - prefix.length - suffix.length;
  if (budget < 40 || !previousTurns.length) return current;
  const context = previousTurns.slice(-4).join("\n").slice(-Math.min(budget, 650));
  return context ? `${prefix}${context}${suffix}${current}` : current;
}
