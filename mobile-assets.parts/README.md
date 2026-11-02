# uneXpected Phone 0.3.0 mobile assets

The numbered `.b64` files in this directory are contiguous chunks of the mobile PWA archive.

The Dockerfile concatenates `part-*.b64` in lexical order, verifies the combined base64 file against SHA-256:

`d9316477b654ea04bc842a2f7ae158b2fffe3eab85f057d7bc3aa7a749f9f55e`

and only then decodes and extracts the archive into `/app/public`. Any missing, truncated, reordered or altered chunk causes the image build to fail before the service starts.

The archive expands to `public/mobile/`, served by the existing gateway's `/mobile/` route. No homepage or TAAFT source is replaced by this asset update.
