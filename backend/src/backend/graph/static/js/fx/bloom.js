// Bloom is an enhancement, never a dependency. The halos already carry the glow,
// so any failure here logs the module that refused and the page carries on.
//
// Two facts decide the numbers below:
//  - the library's composer renders into its own target with no MSAA, so without
//    `samples = 4` turning bloom on turns antialiasing off and the hairlines shimmer;
//  - there is no OutputPass in the vendor set, and none is needed: when bloom is the
//    last pass it redraws its input through a basic material, so base colours and the
//    background stay correct and only the additive glow term is slightly dim.

const HALF = 0.5;

export async function enableBloom(Graph, { strength = 1.05, radius = 0.62, threshold = 0.2 } = {}) {
  let url = 'three/addons/postprocessing/UnrealBloomPass.js';
  try {
    const three = await import('three');
    url = 'three/addons/postprocessing/UnrealBloomPass.js';
    const { UnrealBloomPass } = await import('three/addons/postprocessing/UnrealBloomPass.js');

    const composer = Graph.postProcessingComposer();
    if (!composer || typeof composer.addPass !== 'function') {
      throw new Error('postProcessingComposer() is not available');
    }

    const renderer = Graph.renderer();
    const size = renderer.getSize(new three.Vector2());
    const resolution = new three.Vector2(
      Math.max(64, Math.round(size.x * HALF)),
      Math.max(64, Math.round(size.y * HALF)),
    );

    const pass = new UnrealBloomPass(resolution, strength, radius, threshold);
    composer.addPass(pass);

    // Keep multisampling on the composer's own targets or every 1px link crawls.
    if (composer.renderTarget1) composer.renderTarget1.samples = 4;
    if (composer.renderTarget2) composer.renderTarget2.samples = 4;

    return { ok: true, pass, dispose: () => { composer.removePass(pass); pass.dispose(); } };
  } catch (error) {
    console.info('[atlas] bloom disabled, halos only —', url, String((error && error.message) || error));
    return { ok: false, pass: null, dispose: () => {} };
  }
}

export default enableBloom;
