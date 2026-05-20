import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {};

export default withSentryConfig(nextConfig, {
  org: "aditya-ao",
  project: "javascript-nextjs",

  // Suppress the Sentry CLI output during builds
  silent: !process.env.CI,

  // Upload source maps to Sentry so stack traces show original TS code
  widenClientFileUpload: true,

  // Automatically tree-shake Sentry logger statements in production
  disableLogger: true,
});
