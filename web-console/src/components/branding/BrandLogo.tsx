interface BrandLogoProps {
  variant?: 'icon' | 'wordmark' | 'lockup';
  alt?: string;
  className?: string;
  decorative?: boolean;
}

const BRAND_ASSET_PATHS = {
  icon: '/branding/logo-icon.png',
  wordmark: '/branding/logo-wordmark.png',
  lockup: '/branding/logo-lockup.png',
} as const;

export function BrandLogo({
  variant = 'wordmark',
  alt = 'Amprealize',
  className,
  decorative = false,
}: BrandLogoProps): React.JSX.Element {
  const resolvedClassName = className ? `brand-logo ${className}` : 'brand-logo';

  return (
    <img
      src={BRAND_ASSET_PATHS[variant]}
      alt={decorative ? '' : alt}
      aria-hidden={decorative || undefined}
      className={resolvedClassName}
      decoding="async"
      loading="eager"
    />
  );
}

export default BrandLogo;
