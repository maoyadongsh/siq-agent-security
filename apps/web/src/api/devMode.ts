/** Development identity is never a production authentication mechanism. */
export const DEV_IDENTITY = import.meta.env.DEV && !import.meta.env.PROD
  && import.meta.env.VITE_DEV_MODE === 'true';
