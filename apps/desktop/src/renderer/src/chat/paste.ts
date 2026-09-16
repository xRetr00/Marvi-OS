/**
 * What a paste into the composer means.
 *
 * Windows puts a screenshot on the clipboard as a file with an empty name, so
 * pasting one produced a blank row in the attachment list -- a thing with no
 * name that the user has to guess at. Naming it for the moment it was taken is
 * the whole of this; text pastes are not touched, because the textarea already
 * handles those and intercepting them would break ordinary editing.
 */
export function pastedImages(files: readonly File[], now = new Date()): File[] {
  const images = files.filter((file) => file.type.startsWith('image/'))
  const stamp = now.toISOString().slice(0, 19).replaceAll(':', '-')
  const extension = (type: string): string => (type.split('/')[1] || 'png').split('+')[0]
  return images.map((file, index) =>
    file.name
      ? file
      : new File([file], `pasted-${stamp}${index ? `-${index + 1}` : ''}.${extension(file.type)}`, {
          type: file.type
        })
  )
}
