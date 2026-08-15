/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      {
        source: "/",
        destination: "/design",
        permanent: false,
      },
    ];
  },
};

module.exports = nextConfig;
