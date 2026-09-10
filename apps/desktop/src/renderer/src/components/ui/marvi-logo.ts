/**
 * Marvi's mark, in one place.
 *
 * Its own module rather than a second export from `avatar.tsx` so that file
 * exports only components -- which is what keeps fast refresh working on it,
 * and what the lint rule is actually protecting.
 */
export { default as marviLogo } from '../../assets/app-icon.png'
