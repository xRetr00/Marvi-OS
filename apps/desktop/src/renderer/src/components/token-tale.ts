interface BookScale {
  title: string
  tokens: number
  aside: string
}

const BOOKS: readonly BookScale[] = [
  { title: 'The Very Hungry Caterpillar', tokens: 350, aside: 'The caterpillar remains hungry.' },
  { title: 'The Cat in the Hat', tokens: 2_200, aside: 'The hat is now a context window.' },
  {
    title: 'The Little Prince',
    tokens: 21_000,
    aside: 'Tiny planet, surprisingly efficient prose.'
  },
  {
    title: 'Animal Farm',
    tokens: 40_000,
    aside: 'All tokens are equal; cached tokens are more equal.'
  },
  { title: 'The Hobbit', tokens: 123_000, aside: 'One does not simply walk out of the prompt.' },
  {
    title: 'Pride and Prejudice',
    tokens: 180_000,
    aside: 'It is a truth universally acknowledged by the tokenizer.'
  },
  { title: 'Moby-Dick', tokens: 280_000, aside: 'Call me Tokenmael.' },
  {
    title: 'The Lord of the Rings trilogy',
    tokens: 575_000,
    aside: 'The context is taking the tokens to Isengard.'
  },
  {
    title: 'the complete Sherlock Holmes canon',
    tokens: 800_000,
    aside: 'The missing semicolon was elementary.'
  },
  {
    title: 'the full Harry Potter series',
    tokens: 1_450_000,
    aside: 'Yer a context window, Harry.'
  }
]

export interface TokenTale {
  lead: string
  aside: string
}

export function tokenTale(tokens: number): TokenTale {
  const amount = Number.isFinite(tokens) ? Math.max(0, Math.round(tokens)) : 0
  if (!amount)
    if ($interfaceLocale.get() === 'ar')
      return { lead: 'بطاقة المكتبة لم تُستخدم بعد.', aside: 'شغّل شيئًا مثيرًا للاهتمام.' }
  if (!amount)
    return { lead: 'The library card is untouched.', aside: 'Run something interesting.' }
  const book = [...BOOKS].reverse().find((item) => amount >= item.tokens)
  if (!book)
    return {
      lead: $interfaceLocale.get() === 'ar' ? `استُخدم ${formatNumber(amount)} رمزًا.` : `${formatNumber(amount)} tokens used.`,
      aside: $interfaceLocale.get() === 'ar' ? 'يكفي لإرباك كتاب مصوّر.' : 'Enough to make a picture book nervous.'
    }
  const multiple = amount / book.tokens
  const formatted =
    multiple >= 100
      ? formatNumber(Math.round(multiple))
      : multiple >= 10
        ? formatDecimal(multiple, 1)
        : formatDecimal(multiple, 2)
  if ($interfaceLocale.get() === 'ar')
    return { lead: `استخدمت نحو ${formatted}× من رموز كتاب ${book.title}.`, aside: book.aside }
  return { lead: `You used about ${formatted}× the tokens in ${book.title}.`, aside: book.aside }
}
import { $interfaceLocale, formatDecimal, formatNumber } from '../store/locale'
