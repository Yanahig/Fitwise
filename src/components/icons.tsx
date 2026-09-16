import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;

function Base({ children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={20}
      height={20}
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconDocSearch = (props: IconProps) => (
  <Base {...props}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6" />
    <path d="M14 3v5h5" />
    <path d="M14 3l5 5" />
    <circle cx="16.5" cy="16" r="3" />
    <path d="M19 18.5 21 21" />
  </Base>
);

export const IconTarget = (props: IconProps) => (
  <Base {...props}>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="3.6" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </Base>
);

export const IconRoute = (props: IconProps) => (
  <Base {...props}>
    <circle cx="6" cy="18" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <path d="M8.5 18h4a3.5 3.5 0 0 0 0-7h-1a3.5 3.5 0 0 1 0-7h4" />
  </Base>
);

export const IconFile = (props: IconProps) => (
  <Base {...props}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
  </Base>
);

export const IconNote = (props: IconProps) => (
  <Base {...props}>
    <rect x="4.5" y="3.5" width="15" height="17" rx="2" />
    <path d="M8 8.5h8M8 12h8M8 15.5h5" />
  </Base>
);

export const IconCheck = (props: IconProps) => (
  <Base {...props}>
    <path d="M20 6.5 9.5 17 4 11.5" />
  </Base>
);

export const IconAlert = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 4 3 20h18z" />
    <path d="M12 10v5M12 17.5v.5" />
  </Base>
);

export const IconQuestion = (props: IconProps) => (
  <Base {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.2a2.6 2.6 0 1 1 3.6 2.4c-.7.35-1.1.85-1.1 1.6v.3" />
    <path d="M12 17.2v.3" />
  </Base>
);

export const IconShield = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3.5 5 6v6c0 4 3 7.2 7 8.5 4-1.3 7-4.5 7-8.5V6z" />
    <path d="M12 9v4M12 15.6v.4" />
  </Base>
);

export const IconCase = (props: IconProps) => (
  <Base {...props}>
    <rect x="3.5" y="7.5" width="17" height="12.5" rx="2" />
    <path d="M9 7.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5" />
    <path d="M3.5 12.5h17" />
  </Base>
);

export const IconEvidence = (props: IconProps) => (
  <Base {...props}>
    <path d="M9 4.5h9a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9" />
    <path d="M13 8.5h4M13 12h4M13 15.5h2.5" />
    <circle cx="5.5" cy="12" r="2.5" />
    <path d="M3.4 18.2 7.6 15" />
  </Base>
);

export const IconUsers = (props: IconProps) => (
  <Base {...props}>
    <circle cx="9.5" cy="8.5" r="3" />
    <path d="M3.8 19c.6-3 3-4.6 5.7-4.6S14.6 16 15.2 19" />
    <path d="M16.5 6.5a3 3 0 0 1 0 5.6M18 18.8c-.3-1.6-.9-2.8-1.7-3.6" />
  </Base>
);

export const IconSpark = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3.5l1.7 4.6 4.6 1.7-4.6 1.7L12 16.1l-1.7-4.6L5.7 9.8l4.6-1.7z" />
    <path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" />
  </Base>
);

export const IconArrowRight = (props: IconProps) => (
  <Base {...props}>
    <path d="M5 12h13" />
    <path d="M13 7l5 5-5 5" />
  </Base>
);

export const IconChevronDown = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 9.5l6 6 6-6" />
  </Base>
);

export const IconClose = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Base>
);

export const IconRefresh = (props: IconProps) => (
  <Base {...props}>
    <path d="M20 11a8 8 0 1 0-2.4 6.3" />
    <path d="M20 5.5V11h-5.5" />
  </Base>
);

export const IconLayers = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3.5 3.5 8l8.5 4.5L20.5 8z" />
    <path d="M3.5 12.5 12 17l8.5-4.5" />
    <path d="M3.5 16.8 12 21.3l8.5-4.5" />
  </Base>
);

export const IconSearch = (props: IconProps) => (
  <Base {...props}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Base>
);

export const IconCompass = (props: IconProps) => (
  <Base {...props}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M15.2 8.8l-2 5-5 2 2-5z" />
  </Base>
);

export const IconPlus = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 5v14M5 12h14" />
  </Base>
);
