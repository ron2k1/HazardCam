import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // no floating dev badge: the operator demos from `next dev`, and the badge covers card text at
  // phone width (production builds never show it)
  devIndicators: false,
};

export default nextConfig;
