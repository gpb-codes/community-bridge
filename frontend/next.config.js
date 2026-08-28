/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.API_BASE || "http://backend:8000"}/api/v1/:path*` }];
  },
};
module.exports = nextConfig;
