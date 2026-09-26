/** @type {import('next').NextConfig} */
const backend = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/auth/linkedin/start',
        destination: `${backend}/api/auth/linkedin/start`,
      },
      {
        source: '/api/auth/linkedin/callback',
        destination: `${backend}/api/auth/linkedin/callback`,
      },
      {
        source: '/api/backend/:path*',
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
