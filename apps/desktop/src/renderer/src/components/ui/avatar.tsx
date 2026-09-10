/**
 * A round image with a fallback, on Radix's Avatar.
 *
 * Same three parts as the shadcn component this was adapted from -- Root,
 * Image, Fallback -- with the Tailwind class strings replaced by the classes
 * `chat.css` already owns. There is no `cn` here for the same reason there is
 * no Tailwind: a `className` prop appended to a base class is the whole of
 * what that helper was doing at these three call sites.
 *
 * The fallback matters more than it looks. `AvatarPrimitive.Image` renders
 * nothing until the image actually loads, so without a fallback every avatar
 * is a hole on first paint and a permanent hole if the file ever moves.
 */

import { Avatar as AvatarPrimitive } from 'radix-ui'
import type { ComponentPropsWithoutRef } from 'react'

import { marviLogo } from './marvi-logo'

function classes(base: string, extra?: string): string {
  return extra ? `${base} ${extra}` : base
}

export function Avatar({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>): React.JSX.Element {
  return <AvatarPrimitive.Root className={classes('ui-avatar', className)} {...props} />
}

export function AvatarImage({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>): React.JSX.Element {
  return <AvatarPrimitive.Image className={classes('ui-avatar-image', className)} {...props} />
}

export function AvatarFallback({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback>): React.JSX.Element {
  return (
    <AvatarPrimitive.Fallback className={classes('ui-avatar-fallback', className)} {...props} />
  )
}

/**
 * Marvi's own avatar, so the logo path lives in one place.
 *
 * `delayMs` on the fallback is deliberate: the icon is bundled and resolves in
 * a frame or two, and flashing "M" before it arrives is worse than a beat of
 * empty circle. The fallback is there for the case where it never loads.
 */
export function MarviAvatar({ className }: { className?: string }): React.JSX.Element {
  return (
    <Avatar aria-hidden="true" className={classes('marvi-avatar', className)}>
      <AvatarImage alt="" src={marviLogo} />
      <AvatarFallback delayMs={400}>M</AvatarFallback>
    </Avatar>
  )
}
