/** One-shot Gateway speech. It never opens a Voice room or microphone. */
export async function readAloudWithMarvi(text: string): Promise<void> {
  await window.marvi.readAloud(text)
}

export async function stopMarviReadAloud(): Promise<void> {
  await window.marvi.stopReadAloud()
}
