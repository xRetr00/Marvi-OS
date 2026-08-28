import type { ModelCard } from "../../../shared/runtime"

/**
 * How a model is described in a picker.
 *
 * Lifted out of the Models page so the auxiliary rows show the same thing.
 * They were choosing from the same 415 models with half the information --
 * no context length, no price -- which is the wrong way round: picking a model
 * for a background job is almost entirely a cost decision, and the main model
 * is the one you pick for other reasons.
 */
export function modelContext(tokens: number): string {
  if (!tokens) return ""
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}k ctx` : `${tokens} ctx`
}

export function modelPrice(model: ModelCard): string {
  const prompt = model.promptPerMillion
  const completion = model.completionPerMillion
  if (prompt === null && completion === null) return ""
  if (prompt === 0 && completion === 0) return "free"
  const money = (value: number | null): string =>
    value === null ? "?" : value < 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(1)}`
  return `${money(prompt)}/${money(completion)} per M`
}
