import { readFile } from "node:fs/promises";
//#region ../shared/skin-assets.ts
/** Public, immutable artwork only. Paths come from the shipped allowlist, never from disk traversal. */
function installSkinAssets(ctx, id, directory, files) {
	const prefix = `/skin-assets/${id}`;
	const allowed = new Set(files);
	ctx.inject(["webServer"], (webCtx) => {
		const server = webCtx.get("webServer");
		webCtx.effect(() => server.register({
			kind: "prefix",
			path: prefix,
			handler: async (req, res) => {
				if (req.method !== "GET" && req.method !== "HEAD") {
					res.writeHead(405, { Allow: "GET, HEAD" }).end();
					return;
				}
				const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
				const file = pathname.slice(prefix.length + 1);
				if (!pathname.startsWith(`${prefix}/`) || !allowed.has(file) || !/^[a-f0-9]{64}\.(png|webp)$/.test(file)) {
					res.writeHead(404).end();
					return;
				}
				let bytes;
				try {
					bytes = await readFile(new URL(file, directory));
				} catch (error) {
					if (error.code !== "ENOENT") throw error;
					res.writeHead(404).end();
					return;
				}
				const etag = `"${file.split(".")[0]}"`;
				const headers = {
					"Content-Type": file.endsWith(".webp") ? "image/webp" : "image/png",
					"Cache-Control": "public, max-age=31536000, immutable",
					"X-Content-Type-Options": "nosniff",
					ETag: etag
				};
				if (req.headers["if-none-match"]?.split(",").some((value) => value.trim().replace(/^W\//, "") === etag || value.trim() === "*")) {
					res.writeHead(304, headers).end();
					return;
				}
				res.writeHead(200, {
					...headers,
					"Content-Length": bytes.length
				});
				res.end(req.method === "HEAD" ? void 0 : bytes);
			}
		}), `${id}: packaged artwork`);
	});
}
//#endregion
//#region assets/runtime/manifest.json
var manifest_default = [
	"0c76da127e5f075031194f7b4d1e917fd50ed029ce89f2ed06a1cc370a2ad1dc.webp",
	"1a72373ed9d8aa7ea03788248c51b12191016989bc88cd55dd9b4082e38effaa.webp",
	"296025834038bf230dc1993cb7a4c3426ef137af686cf0e85ab9abb6a4c4935b.webp",
	"3ec0d729e2cfa51f218eb8e04bb7fb3f7bcf99a394f8bd9cb1399592810b6b06.webp",
	"47da3978745e23346661e2f3c9584d75d863d92ee50f1e5572a1f417c197408a.webp",
	"49bd266684ac083baa522ecba5e654c0ca41e1421d9046091d1506755add1a4c.webp",
	"6bfccd4579472ead024603b170a2344f5a701a43d8f4d21043da4dde048b34d7.webp",
	"8e181bcd7243f7f8482f834bda0e02bed610ea0ebf1148190e3c6816fdb71523.webp",
	"b5823400c9a769ce93f1400fd00861eafc91390bb338ac6be83fa2e7ae3ceccf.webp",
	"bcb227be7eddfc09c5cfcdc29bc87190c63c121fb7c2e24a6d94724cf496526d.webp",
	"da801626924381eb6db815c518291e7471d8324dfc4e5c87362fb9ee93d983ac.png",
	"e69dd66de4d8c0bfb1f547659646567c893499301364103ecab2f698c4e6120d.webp",
	"e9d19218b1503762e3fe1b07b747b74c138ab366ecb84a3a8bd1c0367e7f8662.webp",
	"f141d097f2cdf9c32d72aa34caad0b86fe9b83599d34bcbe01cae3805147fcf5.webp",
	"f86603da331eefcc49ee106b35bff7a1f5a1676ecf2f5d8de6e0265963d7e144.webp"
];
//#endregion
//#region src/index.ts
/** Serve only this package's immutable presentation assets while the skin is enabled. */
function apply(ctx) {
	installSkinAssets(ctx, "c137-virus", new URL("../assets/runtime/", import.meta.url), manifest_default);
}
//#endregion
export { apply };
