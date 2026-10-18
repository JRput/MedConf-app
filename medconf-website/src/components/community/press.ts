// Press feedback for the community controls: the shared Button has no
// :active state, so these pressables add scale(0.97) over 160 ms (transform
// named explicitly, never `transition: all`; dropped under reduced motion).
export const PRESS =
  'transition-[background-color,border-color,color,box-shadow,opacity,transform] duration-[160ms] ease-out active:scale-[0.97] motion-reduce:active:scale-100'
