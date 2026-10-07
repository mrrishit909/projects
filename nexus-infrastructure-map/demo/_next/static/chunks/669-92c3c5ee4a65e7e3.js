"use strict";(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[669],{785:(e,t,n)=>{n.d(t,{DY:()=>a,IU:()=>l,uv:()=>s});let r=[];function i(e,t,n=(e,t)=>e===t){if(e===t)return!0;if(!e||!t)return!1;let r=e.length;if(t.length!==r)return!1;for(let i=0;i<r;i++)if(!n(e[i],t[i]))return!1;return!0}function o(e,t=null,n=!1,a={}){for(let o of(null===t&&(t=[e]),r))if(i(t,o.keys,o.equal)){if(n)return;if(Object.prototype.hasOwnProperty.call(o,"error"))throw o.error;if(Object.prototype.hasOwnProperty.call(o,"response"))return a.lifespan&&a.lifespan>0&&(o.timeout&&clearTimeout(o.timeout),o.timeout=setTimeout(o.remove,a.lifespan)),o.response;if(!n)throw o.promise}let s={keys:t,equal:a.equal,remove:()=>{let e=r.indexOf(s);-1!==e&&r.splice(e,1)},promise:("object"==typeof e&&"function"==typeof e.then?e:e(...t)).then(e=>{s.response=e,a.lifespan&&a.lifespan>0&&(s.timeout=setTimeout(s.remove,a.lifespan))}).catch(e=>s.error=e)};if(r.push(s),!n)throw s.promise}let a=(e,t,n)=>o(e,t,!1,n),s=(e,t,n)=>void o(e,t,!0,n),l=e=>{if(void 0===e||0===e.length)r.splice(0,r.length);else{let t=r.find(t=>i(e,t.keys,t.equal));t&&t.remove()}}},2447:(e,t,n)=>{n.d(t,{h:()=>l});var r=n(7620),i=n(3140);let o=e=>{let t,n=new Set,r=(e,r)=>{let i="function"==typeof e?e(t):e;if(!Object.is(i,t)){let e=t;t=(null!=r?r:"object"!=typeof i||null===i)?i:Object.assign({},t,i),n.forEach(n=>n(t,e))}},i=()=>t,o={setState:r,getState:i,getInitialState:()=>a,subscribe:e=>(n.add(e),()=>n.delete(e))},a=t=e(r,i,o);return o},{useSyncExternalStoreWithSelector:a}=i,s=(e,t)=>{let n=e?o(e):o,i=(e,i=t)=>(function(e,t=e=>e,n){let i=a(e.subscribe,e.getState,e.getInitialState,t,n);return r.useDebugValue(i),i})(n,e,i);return Object.assign(i,n),i},l=(e,t)=>e?s(e,t):s},2597:(e,t,n)=>{var r=n(7620),i="function"==typeof Object.is?Object.is:function(e,t){return e===t&&(0!==e||1/e==1/t)||e!=e&&t!=t},o=r.useState,a=r.useEffect,s=r.useLayoutEffect,l=r.useDebugValue;function u(e){var t=e.getSnapshot;e=e.value;try{var n=t();return!i(e,n)}catch(e){return!0}}var c="u"<typeof window||void 0===window.document||void 0===window.document.createElement?function(e,t){return t()}:function(e,t){var n=t(),r=o({inst:{value:n,getSnapshot:t}}),i=r[0].inst,c=r[1];return s(function(){i.value=n,i.getSnapshot=t,u(i)&&c({inst:i})},[e,n,t]),a(function(){return u(i)&&c({inst:i}),e(function(){u(i)&&c({inst:i})})},[e]),l(n),n};t.useSyncExternalStore=void 0!==r.useSyncExternalStore?r.useSyncExternalStore:c},2896:(e,t,n)=>{function r({moduleIds:e}){return null}Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"PreloadChunks",{enumerable:!0,get:function(){return r}}),n(4568),n(7509),n(5999),n(2918),n(2106)},2925:(e,t,n)=>{n.d(t,{default:()=>i.a});var r=n(6446),i=n.n(r)},3121:(e,t,n)=>{n.d(t,{G:()=>o});var r=n(1572),i=n(6339);r.UniformsLib.line={worldUnits:{value:1},linewidth:{value:1},resolution:{value:new i.I9Y},dashOffset:{value:0},dashScale:{value:1},dashSize:{value:1},gapSize:{value:1}},r.ShaderLib.line={uniforms:i.LlO.merge([r.UniformsLib.common,r.UniformsLib.fog,r.UniformsLib.line]),vertexShader:`
		#include <common>
		#include <color_pars_vertex>
		#include <fog_pars_vertex>
		#include <logdepthbuf_pars_vertex>
		#include <clipping_planes_pars_vertex>

		uniform float linewidth;
		uniform vec2 resolution;

		attribute vec3 instanceStart;
		attribute vec3 instanceEnd;

		attribute vec3 instanceColorStart;
		attribute vec3 instanceColorEnd;

		#ifdef WORLD_UNITS

			varying vec4 worldPos;
			varying vec3 worldStart;
			varying vec3 worldEnd;

			#ifdef USE_DASH

				varying vec2 vUv;

			#endif

		#else

			varying vec2 vUv;

		#endif

		#ifdef USE_DASH

			uniform float dashScale;
			attribute float instanceDistanceStart;
			attribute float instanceDistanceEnd;
			varying float vLineDistance;

		#endif

		float trimSegmentAlpha( const in vec4 start, const in vec4 end ) {

			// compute the interpolation factor needed to trim the segment so it terminates
			// between the camera plane and the near plane

			// conservative estimate of the near plane
			float a = projectionMatrix[ 2 ][ 2 ]; // 3nd entry in 3th column
			float b = projectionMatrix[ 3 ][ 2 ]; // 3nd entry in 4th column

			// we need different nearEstimate formula for reversed and default depth buffer
			// a is positive with a reversed depth buffer so it can be used for controlling the code flow
			float nearEstimate = ( a > 0.0 ) ? ( - b / ( a + 1.0 ) ) : ( - 0.5 * b / a );

			return ( nearEstimate - start.z ) / ( end.z - start.z );

		}

		void main() {

			#ifdef USE_COLOR

				vColor.xyz = ( position.y < 0.5 ) ? instanceColorStart : instanceColorEnd;

			#endif

			float aspect = resolution.x / resolution.y;

			// camera space
			vec4 start = modelViewMatrix * vec4( instanceStart, 1.0 );
			vec4 end = modelViewMatrix * vec4( instanceEnd, 1.0 );

			#ifdef USE_DASH

				float lineDistanceStart = dashScale * instanceDistanceStart;
				float lineDistanceEnd = dashScale * instanceDistanceEnd;

			#endif

			#ifdef WORLD_UNITS

				worldStart = start.xyz;
				worldEnd = end.xyz;

			#else

				vUv = uv;

			#endif

			// special case for perspective projection, and segments that terminate either in, or behind, the camera plane
			// clearly the gpu firmware has a way of addressing this issue when projecting into ndc space
			// but we need to perform ndc-space calculations in the shader, so we must address this issue directly
			// perhaps there is a more elegant solution -- WestLangley

			bool perspective = ( projectionMatrix[ 2 ][ 3 ] == - 1.0 ); // 4th entry in the 3rd column

			if ( perspective ) {

				if ( start.z < 0.0 && end.z >= 0.0 ) {

					float alpha = trimSegmentAlpha( start, end );
					end.xyz = mix( start.xyz, end.xyz, alpha );

					#ifdef USE_DASH

						lineDistanceEnd = mix( lineDistanceStart, lineDistanceEnd, alpha );

					#endif

				} else if ( end.z < 0.0 && start.z >= 0.0 ) {

					float alpha = trimSegmentAlpha( end, start );
					start.xyz = mix( end.xyz, start.xyz, alpha );

					#ifdef USE_DASH

						lineDistanceStart = mix( lineDistanceEnd, lineDistanceStart, alpha );

					#endif

				}

			}

			#ifdef USE_DASH

				vLineDistance = ( position.y < 0.5 ) ? lineDistanceStart : lineDistanceEnd;
				vUv = uv;

			#endif

			// clip space
			vec4 clipStart = projectionMatrix * start;
			vec4 clipEnd = projectionMatrix * end;

			// ndc space
			vec3 ndcStart = clipStart.xyz / clipStart.w;
			vec3 ndcEnd = clipEnd.xyz / clipEnd.w;

			// direction
			vec2 dir = ndcEnd.xy - ndcStart.xy;

			// account for clip-space aspect ratio
			dir.x *= aspect;
			dir = normalize( dir );

			#ifdef WORLD_UNITS

				vec3 worldDir = normalize( end.xyz - start.xyz );
				vec3 tmpFwd = normalize( mix( start.xyz, end.xyz, 0.5 ) );
				vec3 worldUp = normalize( cross( worldDir, tmpFwd ) );
				vec3 worldFwd = cross( worldDir, worldUp );
				worldPos = position.y < 0.5 ? start: end;

				// height offset
				float hw = linewidth * 0.5;
				worldPos.xyz += position.x < 0.0 ? hw * worldUp : - hw * worldUp;

				// don't extend the line if we're rendering dashes because we
				// won't be rendering the endcaps
				#ifndef USE_DASH

					// cap extension
					worldPos.xyz += position.y < 0.5 ? - hw * worldDir : hw * worldDir;

					// add width to the box
					worldPos.xyz += worldFwd * hw;

					// endcaps
					if ( position.y > 1.0 || position.y < 0.0 ) {

						worldPos.xyz -= worldFwd * 2.0 * hw;

					}

				#endif

				// project the worldpos
				vec4 clip = projectionMatrix * worldPos;

				// shift the depth of the projected points so the line
				// segments overlap neatly
				vec3 clipPose = ( position.y < 0.5 ) ? ndcStart : ndcEnd;
				clip.z = clipPose.z * clip.w;

			#else

				vec2 offset = vec2( dir.y, - dir.x );
				// undo aspect ratio adjustment
				dir.x /= aspect;
				offset.x /= aspect;

				// sign flip
				if ( position.x < 0.0 ) offset *= - 1.0;

				// endcaps
				if ( position.y < 0.0 ) {

					offset += - dir;

				} else if ( position.y > 1.0 ) {

					offset += dir;

				}

				// adjust for linewidth
				offset *= linewidth;

				// adjust for clip-space to screen-space conversion // maybe resolution should be based on viewport ...
				offset /= resolution.y;

				// select end
				vec4 clip = ( position.y < 0.5 ) ? clipStart : clipEnd;

				// back to clip space
				offset *= clip.w;

				clip.xy += offset;

			#endif

			gl_Position = clip;

			vec4 mvPosition = ( position.y < 0.5 ) ? start : end; // this is an approximation

			#include <logdepthbuf_vertex>
			#include <clipping_planes_vertex>
			#include <fog_vertex>

		}
		`,fragmentShader:`
		uniform vec3 diffuse;
		uniform float opacity;
		uniform float linewidth;

		#ifdef USE_DASH

			uniform float dashOffset;
			uniform float dashSize;
			uniform float gapSize;

		#endif

		varying float vLineDistance;

		#ifdef WORLD_UNITS

			varying vec4 worldPos;
			varying vec3 worldStart;
			varying vec3 worldEnd;

			#ifdef USE_DASH

				varying vec2 vUv;

			#endif

		#else

			varying vec2 vUv;

		#endif

		#include <common>
		#include <color_pars_fragment>
		#include <fog_pars_fragment>
		#include <logdepthbuf_pars_fragment>
		#include <clipping_planes_pars_fragment>

		vec2 closestLineToLine(vec3 p1, vec3 p2, vec3 p3, vec3 p4) {

			float mua;
			float mub;

			vec3 p13 = p1 - p3;
			vec3 p43 = p4 - p3;

			vec3 p21 = p2 - p1;

			float d1343 = dot( p13, p43 );
			float d4321 = dot( p43, p21 );
			float d1321 = dot( p13, p21 );
			float d4343 = dot( p43, p43 );
			float d2121 = dot( p21, p21 );

			float denom = d2121 * d4343 - d4321 * d4321;

			float numer = d1343 * d4321 - d1321 * d4343;

			mua = numer / denom;
			mua = clamp( mua, 0.0, 1.0 );
			mub = ( d1343 + d4321 * ( mua ) ) / d4343;
			mub = clamp( mub, 0.0, 1.0 );

			return vec2( mua, mub );

		}

		void main() {

			float alpha = opacity;
			vec4 diffuseColor = vec4( diffuse, alpha );

			#include <clipping_planes_fragment>

			#ifdef USE_DASH

				if ( vUv.y < - 1.0 || vUv.y > 1.0 ) discard; // discard endcaps

				if ( mod( vLineDistance + dashOffset, dashSize + gapSize ) > dashSize ) discard; // todo - FIX

			#endif

			#ifdef WORLD_UNITS

				// Find the closest points on the view ray and the line segment
				vec3 rayEnd = normalize( worldPos.xyz ) * 1e5;
				vec3 lineDir = worldEnd - worldStart;
				vec2 params = closestLineToLine( worldStart, worldEnd, vec3( 0.0, 0.0, 0.0 ), rayEnd );

				vec3 p1 = worldStart + lineDir * params.x;
				vec3 p2 = rayEnd * params.y;
				vec3 delta = p1 - p2;
				float len = length( delta );
				float norm = len / linewidth;

				#ifndef USE_DASH

					#ifdef USE_ALPHA_TO_COVERAGE

						float dnorm = fwidth( norm );
						alpha = 1.0 - smoothstep( 0.5 - dnorm, 0.5 + dnorm, norm );

					#else

						if ( norm > 0.5 ) {

							discard;

						}

					#endif

				#endif

			#else

				#ifdef USE_ALPHA_TO_COVERAGE

					// artifacts appear on some hardware if a derivative is taken within a conditional
					float a = vUv.x;
					float b = ( vUv.y > 0.0 ) ? vUv.y - 1.0 : vUv.y + 1.0;
					float len2 = a * a + b * b;
					float dlen = fwidth( len2 );

					if ( abs( vUv.y ) > 1.0 ) {

						alpha = 1.0 - smoothstep( 1.0 - dlen, 1.0 + dlen, len2 );

					}

				#else

					if ( abs( vUv.y ) > 1.0 ) {

						float a = vUv.x;
						float b = ( vUv.y > 0.0 ) ? vUv.y - 1.0 : vUv.y + 1.0;
						float len2 = a * a + b * b;

						if ( len2 > 1.0 ) discard;

					}

				#endif

			#endif

			#include <logdepthbuf_fragment>
			#include <color_fragment>

			gl_FragColor = vec4( diffuseColor.rgb, alpha );

			#include <tonemapping_fragment>
			#include <colorspace_fragment>
			#include <fog_fragment>
			#include <premultiplied_alpha_fragment>

		}
		`};class o extends i.BKk{constructor(e){super({type:"LineMaterial",uniforms:i.LlO.clone(r.ShaderLib.line.uniforms),vertexShader:r.ShaderLib.line.vertexShader,fragmentShader:r.ShaderLib.line.fragmentShader,clipping:!0}),this.isLineMaterial=!0,this.setValues(e)}get color(){return this.uniforms.diffuse.value}set color(e){this.uniforms.diffuse.value=e}get worldUnits(){return"WORLD_UNITS"in this.defines}set worldUnits(e){!0===e!==this.worldUnits&&(this.needsUpdate=!0),!0===e?this.defines.WORLD_UNITS="":delete this.defines.WORLD_UNITS}get linewidth(){return this.uniforms.linewidth.value}set linewidth(e){this.uniforms.linewidth&&(this.uniforms.linewidth.value=e)}get dashed(){return"USE_DASH"in this.defines}set dashed(e){!0===e!==this.dashed&&(this.needsUpdate=!0),!0===e?this.defines.USE_DASH="":delete this.defines.USE_DASH}get dashScale(){return this.uniforms.dashScale.value}set dashScale(e){this.uniforms.dashScale.value=e}get dashSize(){return this.uniforms.dashSize.value}set dashSize(e){this.uniforms.dashSize.value=e}get dashOffset(){return this.uniforms.dashOffset.value}set dashOffset(e){this.uniforms.dashOffset.value=e}get gapSize(){return this.uniforms.gapSize.value}set gapSize(e){this.uniforms.gapSize.value=e}get opacity(){return this.uniforms.opacity.value}set opacity(e){this.uniforms&&(this.uniforms.opacity.value=e)}get resolution(){return this.uniforms.resolution.value}set resolution(e){this.uniforms.resolution.value.copy(e)}get alphaToCoverage(){return"USE_ALPHA_TO_COVERAGE"in this.defines}set alphaToCoverage(e){this.defines&&(!0===e!==this.alphaToCoverage&&(this.needsUpdate=!0),!0===e?this.defines.USE_ALPHA_TO_COVERAGE="":delete this.defines.USE_ALPHA_TO_COVERAGE)}}},3140:(e,t,n)=>{e.exports=n(8558)},3242:(e,t,n)=>{n.d(t,{n:()=>a});var r=n(6339);let i=new r.NRn,o=new r.Pq0;class a extends r.CmU{constructor(){super(),this.isLineSegmentsGeometry=!0,this.type="LineSegmentsGeometry",this.setIndex([0,2,1,2,3,1,2,4,3,4,5,3,4,6,5,6,7,5]),this.setAttribute("position",new r.qtW([-1,2,0,1,2,0,-1,1,0,1,1,0,-1,0,0,1,0,0,-1,-1,0,1,-1,0],3)),this.setAttribute("uv",new r.qtW([-1,2,1,2,-1,1,1,1,-1,-1,1,-1,-1,-2,1,-2],2))}applyMatrix4(e){let t=this.attributes.instanceStart,n=this.attributes.instanceEnd;return void 0!==t&&(t.applyMatrix4(e),n.applyMatrix4(e),t.needsUpdate=!0),null!==this.boundingBox&&this.computeBoundingBox(),null!==this.boundingSphere&&this.computeBoundingSphere(),this}setPositions(e){let t;e instanceof Float32Array?t=e:Array.isArray(e)&&(t=new Float32Array(e));let n=new r.LuO(t,6,1);return this.setAttribute("instanceStart",new r.eHs(n,3,0)),this.setAttribute("instanceEnd",new r.eHs(n,3,3)),this.instanceCount=this.attributes.instanceStart.count,this.computeBoundingBox(),this.computeBoundingSphere(),this}setColors(e){let t;e instanceof Float32Array?t=e:Array.isArray(e)&&(t=new Float32Array(e));let n=new r.LuO(t,6,1);return this.setAttribute("instanceColorStart",new r.eHs(n,3,0)),this.setAttribute("instanceColorEnd",new r.eHs(n,3,3)),this}fromWireframeGeometry(e){return this.setPositions(e.attributes.position.array),this}fromEdgesGeometry(e){return this.setPositions(e.attributes.position.array),this}fromMesh(e){return this.fromWireframeGeometry(new r.XJ7(e.geometry)),this}fromLineSegments(e){let t=e.geometry;return this.setPositions(t.attributes.position.array),this}computeBoundingBox(){null===this.boundingBox&&(this.boundingBox=new r.NRn);let e=this.attributes.instanceStart,t=this.attributes.instanceEnd;void 0!==e&&void 0!==t&&(this.boundingBox.setFromBufferAttribute(e),i.setFromBufferAttribute(t),this.boundingBox.union(i))}computeBoundingSphere(){null===this.boundingSphere&&(this.boundingSphere=new r.iyt),null===this.boundingBox&&this.computeBoundingBox();let e=this.attributes.instanceStart,t=this.attributes.instanceEnd;if(void 0!==e&&void 0!==t){let n=this.boundingSphere.center;this.boundingBox.getCenter(n);let r=0;for(let i=0,a=e.count;i<a;i++)o.fromBufferAttribute(e,i),r=Math.max(r,n.distanceToSquared(o)),o.fromBufferAttribute(t,i),r=Math.max(r,n.distanceToSquared(o));this.boundingSphere.radius=Math.sqrt(r),isNaN(this.boundingSphere.radius)&&console.error("THREE.LineSegmentsGeometry.computeBoundingSphere(): Computed radius is NaN. The instanced position data is likely to have NaN values.",this)}}toJSON(){}}},3245:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0});var n={createReactBrowserBailoutReason:function(){return o},getReactBrowserBailoutReason:function(){return a},isNextBrowserBailoutError:function(){return s}};for(var r in n)Object.defineProperty(t,r,{enumerable:!0,get:n[r]});let i=Symbol.for("next.browser-bailout-reason");function o(e){return{$$typeof:i,reason:e}}function a(e){let t=e?.cause;return t?.$$typeof===i?t.reason:void 0}function s(e){return void 0!==a(e)}},3597:(e,t,n)=>{Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"BailoutToCSRForNextDynamic",{enumerable:!0,get:function(){return a}});let r=n(7620),i=n(7509);n(1841);let o=n(3245).createReactBrowserBailoutReason.bind(null,"next/dynamic");function a({children:e}){return(0,r.use)((0,i.browser)(o)),e}},4594:(e,t,n)=>{e.exports=n(7995)},5516:(e,t,n)=>{n.d(t,{v:()=>i});var r=n(3242);class i extends r.n{constructor(){super(),this.isLineGeometry=!0,this.type="LineGeometry"}setPositions(e){let t=e.length-3,n=new Float32Array(2*t);for(let r=0;r<t;r+=3)n[2*r]=e[r],n[2*r+1]=e[r+1],n[2*r+2]=e[r+2],n[2*r+3]=e[r+3],n[2*r+4]=e[r+4],n[2*r+5]=e[r+5];return super.setPositions(n),this}setColors(e){let t=e.length-3,n=new Float32Array(2*t);for(let r=0;r<t;r+=3)n[2*r]=e[r],n[2*r+1]=e[r+1],n[2*r+2]=e[r+2],n[2*r+3]=e[r+3],n[2*r+4]=e[r+4],n[2*r+5]=e[r+5];return super.setColors(n),this}setFromPoints(e){let t=e.length-1,n=new Float32Array(6*t);for(let r=0;r<t;r++)n[6*r]=e[r].x,n[6*r+1]=e[r].y,n[6*r+2]=e[r].z||0,n[6*r+3]=e[r+1].x,n[6*r+4]=e[r+1].y,n[6*r+5]=e[r+1].z||0;return super.setPositions(n),this}fromLine(e){let t=e.geometry;return this.setPositions(t.attributes.position.array),this}}},5999:(e,t,n)=>{Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"workAsyncStorage",{enumerable:!0,get:function(){return r.workAsyncStorageInstance}});let r=n(6035)},6035:(e,t,n)=>{Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"workAsyncStorageInstance",{enumerable:!0,get:function(){return r}});let r=(0,n(9113).getOrCreateGlobalAsyncLocalStorage)("work-async-storage")},6446:(e,t,n)=>{Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"default",{enumerable:!0,get:function(){return i}});let r=n(4468)._(n(7926));function i(e,t){let n={};"function"==typeof e&&(n.loader=e);let i={...n,...t};return(0,r.default)({...i,modules:i.loadableGenerated?.modules})}("function"==typeof t.default||"object"==typeof t.default&&null!==t.default)&&void 0===t.default.__esModule&&(Object.defineProperty(t.default,"__esModule",{value:!0}),Object.assign(t.default,t),e.exports=t.default)},6546:(e,t,n)=>{n.d(t,{Hl:()=>d});var r=n(5319),i=n(7620),o=n(1572);function a(e,t){let n;return(...r)=>{window.clearTimeout(n),n=window.setTimeout(()=>e(...r),t)}}let s=["x","y","top","bottom","left","right","width","height"];var l=n(7479),u=n(4568);function c({ref:e,children:t,fallback:n,resize:l,style:d,gl:f,events:p=r.f,eventSource:h,eventPrefix:m,shadows:v,linear:y,flat:b,legacy:w,orthographic:g,frameloop:S,dpr:x,performance:E,raycaster:_,camera:z,scene:A,onPointerMissed:L,onCreated:O,...P}){i.useMemo(()=>(0,r.e)(o),[]);let U=(0,r.u)(),[j,M]=function({debounce:e,scroll:t,polyfill:n,offsetSize:r}={debounce:0,scroll:!1,offsetSize:!1}){var o,l,u;let c=n||("u"<typeof window?class{}:window.ResizeObserver);if(!c)throw Error("This browser does not support ResizeObserver out of the box. See: https://github.com/react-spring/react-use-measure/#resize-observer-polyfills");let[d,f]=(0,i.useState)({left:0,top:0,width:0,height:0,bottom:0,right:0,x:0,y:0}),p=(0,i.useRef)({element:null,scrollContainers:null,resizeObserver:null,lastBounds:d,orientationHandler:null}),h=e?"number"==typeof e?e:e.scroll:null,m=e?"number"==typeof e?e:e.resize:null,v=(0,i.useRef)(!1);(0,i.useEffect)(()=>(v.current=!0,()=>void(v.current=!1)));let[y,b,w]=(0,i.useMemo)(()=>{let e=()=>{let e,t;if(!p.current.element)return;let{left:n,top:i,width:o,height:a,bottom:l,right:u,x:c,y:d}=p.current.element.getBoundingClientRect(),h={left:n,top:i,width:o,height:a,bottom:l,right:u,x:c,y:d};p.current.element instanceof HTMLElement&&r&&(h.height=p.current.element.offsetHeight,h.width=p.current.element.offsetWidth),Object.freeze(h),v.current&&(e=p.current.lastBounds,t=h,!s.every(n=>e[n]===t[n]))&&f(p.current.lastBounds=h)};return[e,m?a(e,m):e,h?a(e,h):e]},[f,r,h,m]);function g(){p.current.scrollContainers&&(p.current.scrollContainers.forEach(e=>e.removeEventListener("scroll",w,!0)),p.current.scrollContainers=null),p.current.resizeObserver&&(p.current.resizeObserver.disconnect(),p.current.resizeObserver=null),p.current.orientationHandler&&("orientation"in screen&&"removeEventListener"in screen.orientation?screen.orientation.removeEventListener("change",p.current.orientationHandler):"onorientationchange"in window&&window.removeEventListener("orientationchange",p.current.orientationHandler))}function S(){p.current.element&&(p.current.resizeObserver=new c(w),p.current.resizeObserver.observe(p.current.element),t&&p.current.scrollContainers&&p.current.scrollContainers.forEach(e=>e.addEventListener("scroll",w,{capture:!0,passive:!0})),p.current.orientationHandler=()=>{w()},"orientation"in screen&&"addEventListener"in screen.orientation?screen.orientation.addEventListener("change",p.current.orientationHandler):"onorientationchange"in window&&window.addEventListener("orientationchange",p.current.orientationHandler))}return o=w,l=!!t,(0,i.useEffect)(()=>{if(l)return window.addEventListener("scroll",o,{capture:!0,passive:!0}),()=>void window.removeEventListener("scroll",o,!0)},[o,l]),u=b,(0,i.useEffect)(()=>(window.addEventListener("resize",u),()=>void window.removeEventListener("resize",u)),[u]),(0,i.useEffect)(()=>{g(),S()},[t,w,b]),(0,i.useEffect)(()=>g,[]),[e=>{e&&e!==p.current.element&&(g(),p.current.element=e,p.current.scrollContainers=function e(t){let n=[];if(!t||t===document.body)return n;let{overflow:r,overflowX:i,overflowY:o}=window.getComputedStyle(t);return[r,i,o].some(e=>"auto"===e||"scroll"===e)&&n.push(t),[...n,...e(t.parentElement)]}(e),S())},d,y]}({scroll:!0,debounce:{scroll:50,resize:0},...l}),T=i.useRef(null),B=i.useRef(null);i.useImperativeHandle(e,()=>T.current);let C=(0,r.a)(L),D=i.useCallback(e=>null==C.current?void 0:C.current(e),[C]),[k,R]=i.useState(!1),[I,H]=i.useState(!1);if(k)throw k;if(I)throw I;let F=i.useRef(null),[N,q]=(0,r.b)(),W=i.useRef(null),G=()=>h?(0,r.i)(h)?h.current:h:B.current;i.useInsertionEffect(()=>()=>{let e=F.current;F.current=null,null==e||e.unmount()},[]),(0,r.c)(()=>{let e=T.current;M.width>0&&M.height>0&&e&&(F.current||(F.current=(0,r.d)(e)),F.current.configure({gl:f,scene:A,events:p,shadows:v,linear:y,flat:b,legacy:w,orthographic:g,frameloop:S,dpr:x,performance:E,raycaster:_,camera:z,size:M,onPointerMissed:D,onCreated:e=>{var t;W.current=e,null==e.events.connect||e.events.connect(null!=(t=G())?t:B.current),m&&e.setEvents({compute:(e,t)=>{let n=e[m+"X"],r=e[m+"Y"];t.pointer.set(n/t.size.width*2-1,-(2*(r/t.size.height))+1),t.raycaster.setFromCamera(t.pointer,t.camera)}}),null==O||O(e)}}).catch(H),"fulfilled"===F.current.ready.status?F.current.render((0,u.jsx)(U,{children:(0,u.jsx)(r.E,{set:H,children:(0,u.jsx)(i.Suspense,{fallback:(0,u.jsx)(r.B,{set:R}),children:null!=t?t:null})})})):"pending"===F.current.ready.status&&q(F.current.ready))}),i.useEffect(()=>{var e;let t=null==(e=W.current)?void 0:e.get(),n=G();t&&n&&t.events.connected!==n&&(null==t.events.connect||t.events.connect(n))}),i.useEffect(()=>{let e=T.current;return()=>{var t;e.isConnected||null==(t=F.current)||t.unmount()}},[]);let V=h?"none":"auto";return(0,u.jsxs)("div",{ref:B,style:{position:"relative",width:"100%",height:"100%",overflow:"hidden",pointerEvents:V,...d},...P,children:[(0,u.jsx)("div",{ref:j,style:{width:"100%",height:"100%"},children:(0,u.jsx)("canvas",{ref:T,style:{display:"block"},children:n})}),N]})}function d(e){return(0,u.jsx)(l.Af,{children:(0,u.jsx)(c,{...e})})}n(4594)},6574:(e,t,n)=>{e.exports=n(2597)},7479:(e,t,n)=>{n.d(t,{Af:()=>u,Go:()=>h,Nz:()=>a,u5:()=>c,y3:()=>p});var r,i,o=n(7620);function a(e,t,n){if(!e)return;if(!0===n(e))return e;let r=t?e.return:e.child;for(;r;){let e=a(r,t,n);if(e)return e;r=t?null:r.sibling}}function s(e){try{return Object.defineProperties(e,{_currentRenderer:{get:()=>null,set(){}},_currentRenderer2:{get:()=>null,set(){}}})}catch(t){return e}}"u">typeof window&&((null==(r=window.document)?void 0:r.createElement)||(null==(i=window.navigator)?void 0:i.product)==="ReactNative")?o.useLayoutEffect:o.useEffect;let l=s(o.createContext(null));class u extends o.Component{render(){return o.createElement(l.Provider,{value:this._reactInternals},this.props.children)}}function c(){let e=o.useContext(l);if(null===e)throw Error("its-fine: useFiber must be called within a <FiberProvider />!");let t=o.useId();return o.useMemo(()=>{for(let n of[e,null==e?void 0:e.alternate]){if(!n)continue;let e=a(n,!1,e=>{let n=e.memoizedState;for(;n;){if(n.memoizedState===t)return!0;n=n.next}});if(e)return e}},[e,t])}let d=Symbol.for("react.context"),f=e=>null!==e&&"object"==typeof e&&"$$typeof"in e&&e.$$typeof===d;function p(){let e=function(){let e=c(),[t]=o.useState(()=>new Map);t.clear();let n=e;for(;n;){let e=n.type;f(e)&&e!==l&&!t.has(e)&&t.set(e,o.use(s(e))),n=n.return}return t}();return o.useMemo(()=>Array.from(e.keys()).reduce((t,n)=>r=>o.createElement(t,null,o.createElement(n.Provider,{...r,value:e.get(n)})),e=>o.createElement(u,{...e})),[e])}function h(){if(!o.Activity)throw Error("its-fine: useActivityBridge requires React 19.2 or later!");let e=c(),[t]=o.useState(()=>{let t,n=[],r=!1;a(e,!0,e=>{var t,i;if(e.elementType===o.Activity){let r=(null==(t=e.child)?void 0:t.tag)===22?e.child.stateNode:null;if("number"!=typeof(null==r?void 0:r._visibility))throw Error("its-fine: unsupported React Activity internals!");n.push(r)}else 22===e.tag&&(null==(i=e.return)?void 0:i.elementType)!==o.Activity&&(r=!0)});let i="hidden",s=new Set,l={mounted:!1,connected:!1,subscribe:e=>(s.add(e),()=>{s.delete(e)}),sync(e){l.mounted&&!l.connected&&r&&n.length>0?t||(t=function(e){if("function"==typeof requestAnimationFrame){let t=requestAnimationFrame(e);return()=>cancelAnimationFrame(t)}let t=setTimeout(e,16);return()=>clearTimeout(t)}(()=>{t=void 0,l.sync(!0)})):(null==t||t(),t=void 0);let o=i;if(l.mounted?l.connected?o="visible":e&&(o=n.every(e=>(1&e._visibility)!=0)?"visible":"hidden"):o="hidden",i!==o)for(let e of(i=o,s))e()},Bridge:({children:e})=>o.createElement(o.Activity,{mode:o.useSyncExternalStore(l.subscribe,()=>i,()=>"hidden")},e)};return l});return o.useInsertionEffect(()=>(t.mounted=!0,queueMicrotask(()=>t.sync(!1)),()=>{t.mounted=!1,queueMicrotask(()=>t.sync(!1))}),[t]),o.useLayoutEffect(()=>(t.connected=!0,t.sync(!1),()=>{t.connected=!1,t.sync(!0)}),[t]),t.Bridge}},7926:(e,t,n)=>{Object.defineProperty(t,"__esModule",{value:!0}),Object.defineProperty(t,"default",{enumerable:!0,get:function(){return l}});let r=n(4568),i=n(7620),o=n(3597);function a(e){return{default:e&&"default"in e?e.default:e}}n(2896);let s={loader:()=>Promise.resolve(a(()=>null)),loading:null,ssr:!0},l=function(e){let t={...s,...e},n=(0,i.lazy)(()=>t.loader().then(a)),l=t.loading;function u(e){let a=l?(0,r.jsx)(l,{isLoading:!0,pastDelay:!0,error:null}):null,s=!t.ssr||!!t.loading,u=s?i.Suspense:i.Fragment,c=t.ssr?(0,r.jsxs)(r.Fragment,{children:[null,(0,r.jsx)(n,{...e})]}):(0,r.jsx)(o.BailoutToCSRForNextDynamic,{children:(0,r.jsx)(n,{...e})});return(0,r.jsx)(u,{...s?{fallback:a}:{},children:c})}return u.displayName="LoadableComponent",u}},7995:(e,t)=>{function n(e,t){var n=e.length;for(e.push(t);0<n;){var r=n-1>>>1,i=e[r];if(0<o(i,t))e[r]=t,e[n]=i,n=r;else break}}function r(e){return 0===e.length?null:e[0]}function i(e){if(0===e.length)return null;var t=e[0],n=e.pop();if(n!==t){e[0]=n;for(var r=0,i=e.length,a=i>>>1;r<a;){var s=2*(r+1)-1,l=e[s],u=s+1,c=e[u];if(0>o(l,n))u<i&&0>o(c,l)?(e[r]=c,e[u]=n,r=u):(e[r]=l,e[s]=n,r=s);else if(u<i&&0>o(c,n))e[r]=c,e[u]=n,r=u;else break}}return t}function o(e,t){var n=e.sortIndex-t.sortIndex;return 0!==n?n:e.id-t.id}if(t.unstable_now=void 0,"object"==typeof performance&&"function"==typeof performance.now){var a,s=performance;t.unstable_now=function(){return s.now()}}else{var l=Date,u=l.now();t.unstable_now=function(){return l.now()-u}}var c=[],d=[],f=1,p=null,h=3,m=!1,v=!1,y=!1,b=!1,w="function"==typeof setTimeout?setTimeout:null,g="function"==typeof clearTimeout?clearTimeout:null,S="u">typeof setImmediate?setImmediate:null;function x(e){for(var t=r(d);null!==t;){if(null===t.callback)i(d);else if(t.startTime<=e)i(d),t.sortIndex=t.expirationTime,n(c,t);else break;t=r(d)}}function E(e){if(y=!1,x(e),!v)if(null!==r(c))v=!0,_||(_=!0,a());else{var t=r(d);null!==t&&M(E,t.startTime-e)}}var _=!1,z=-1,A=5,L=-1;function O(){return!!b||!(t.unstable_now()-L<A)}function P(){if(b=!1,_){var e=t.unstable_now();L=e;var n=!0;try{e:{v=!1,y&&(y=!1,g(z),z=-1),m=!0;var o=h;try{t:{for(x(e),p=r(c);null!==p&&!(p.expirationTime>e&&O());){var s=p.callback;if("function"==typeof s){p.callback=null,h=p.priorityLevel;var l=s(p.expirationTime<=e);if(e=t.unstable_now(),"function"==typeof l){p.callback=l,x(e),n=!0;break t}p===r(c)&&i(c),x(e)}else i(c);p=r(c)}if(null!==p)n=!0;else{var u=r(d);null!==u&&M(E,u.startTime-e),n=!1}}break e}finally{p=null,h=o,m=!1}}}finally{n?a():_=!1}}}if("function"==typeof S)a=function(){S(P)};else if("u">typeof MessageChannel){var U=new MessageChannel,j=U.port2;U.port1.onmessage=P,a=function(){j.postMessage(null)}}else a=function(){w(P,0)};function M(e,n){z=w(function(){e(t.unstable_now())},n)}t.unstable_IdlePriority=5,t.unstable_ImmediatePriority=1,t.unstable_LowPriority=4,t.unstable_NormalPriority=3,t.unstable_Profiling=null,t.unstable_UserBlockingPriority=2,t.unstable_cancelCallback=function(e){e.callback=null},t.unstable_forceFrameRate=function(e){0>e||125<e?console.error("forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported"):A=0<e?Math.floor(1e3/e):5},t.unstable_getCurrentPriorityLevel=function(){return h},t.unstable_next=function(e){switch(h){case 1:case 2:case 3:var t=3;break;default:t=h}var n=h;h=t;try{return e()}finally{h=n}},t.unstable_requestPaint=function(){b=!0},t.unstable_runWithPriority=function(e,t){switch(e){case 1:case 2:case 3:case 4:case 5:break;default:e=3}var n=h;h=e;try{return t()}finally{h=n}},t.unstable_scheduleCallback=function(e,i,o){var s=t.unstable_now();switch(o="object"==typeof o&&null!==o&&"number"==typeof(o=o.delay)&&0<o?s+o:s,e){case 1:var l=-1;break;case 2:l=250;break;case 5:l=0x3fffffff;break;case 4:l=1e4;break;default:l=5e3}return l=o+l,e={id:f++,callback:i,priorityLevel:e,startTime:o,expirationTime:l,sortIndex:-1},o>s?(e.sortIndex=o,n(d,e),null===r(c)&&e===r(d)&&(y?(g(z),z=-1):y=!0,M(E,o-s))):(e.sortIndex=l,n(c,e),v||m||(v=!0,_||(_=!0,a()))),e},t.unstable_shouldYield=O,t.unstable_wrapCallback=function(e){var t=h;return function(){var n=h;h=t;try{return e.apply(this,arguments)}finally{h=n}}}},8558:(e,t,n)=>{var r=n(7620),i=n(6574),o="function"==typeof Object.is?Object.is:function(e,t){return e===t&&(0!==e||1/e==1/t)||e!=e&&t!=t},a=i.useSyncExternalStore,s=r.useRef,l=r.useEffect,u=r.useMemo,c=r.useDebugValue;t.useSyncExternalStoreWithSelector=function(e,t,n,r,i){var d=s(null);if(null===d.current){var f={hasValue:!1,value:null};d.current=f}else f=d.current;var p=a(e,(d=u(function(){function e(e){if(!l){if(l=!0,a=e,e=r(e),void 0!==i&&f.hasValue){var t=f.value;if(i(t,e))return s=t}return s=e}if(t=s,o(a,e))return t;var n=r(e);return void 0!==i&&i(t,n)?(a=e,t):(a=e,s=n)}var a,s,l=!1,u=void 0===n?null:n;return[function(){return e(t())},null===u?void 0:function(){return e(u())}]},[t,n,r,i]))[0],d[1]);return l(function(){f.hasValue=!0,f.value=p},[p]),c(p),p}},8844:(e,t,n)=>{let r,i;n.d(t,{X:()=>_});var o=n(6339),a=n(3242),s=n(3121);let l=new o.IUQ,u=new o.Pq0,c=new o.Pq0,d=new o.IUQ,f=new o.IUQ,p=new o.IUQ,h=new o.Pq0,m=new o.kn4,v=new o.cZY,y=new o.Pq0,b=new o.NRn,w=new o.iyt,g=new o.IUQ;function S(e,t,n){return g.set(0,0,-t,1).applyMatrix4(e.projectionMatrix),g.multiplyScalar(1/g.w),g.x=i/n.width,g.y=i/n.height,g.applyMatrix4(e.projectionMatrixInverse),g.multiplyScalar(1/g.w),Math.abs(Math.max(g.x,g.y))}class x extends o.eaF{constructor(e=new a.n,t=new s.G({color:0xffffff*Math.random()})){super(e,t),this.isLineSegments2=!0,this.type="LineSegments2"}computeLineDistances(){let e=this.geometry,t=e.attributes.instanceStart,n=e.attributes.instanceEnd,r=new Float32Array(2*t.count);for(let e=0,i=0,o=t.count;e<o;e++,i+=2)u.fromBufferAttribute(t,e),c.fromBufferAttribute(n,e),r[i]=0===i?0:r[i-1],r[i+1]=r[i]+u.distanceTo(c);let i=new o.LuO(r,2,1);return e.setAttribute("instanceDistanceStart",new o.eHs(i,1,0)),e.setAttribute("instanceDistanceEnd",new o.eHs(i,1,1)),this}raycast(e,t){let n,a,s=this.material.worldUnits,l=e.camera;if(null!==l||s||console.error('LineSegments2: "Raycaster.camera" needs to be set in order to raycast against LineSegments2 while worldUnits is set to false.'),!1===s&&(0===this.material.resolution.x||0===this.material.resolution.y))return;let u=void 0!==e.params.Line2&&e.params.Line2.threshold||0;r=e.ray;let c=this.matrixWorld,g=this.geometry,x=this.material;if(i=x.linewidth+u,null===g.boundingSphere&&g.computeBoundingSphere(),w.copy(g.boundingSphere).applyMatrix4(c),s)n=.5*i;else{let e=Math.max(l.near,w.distanceToPoint(r.origin));n=S(l,e,x.resolution)}if(w.radius+=n,!1!==r.intersectsSphere(w)){if(null===g.boundingBox&&g.computeBoundingBox(),b.copy(g.boundingBox).applyMatrix4(c),s)a=.5*i;else{let e=Math.max(l.near,b.distanceToPoint(r.origin));a=S(l,e,x.resolution)}b.expandByScalar(a),!1!==r.intersectsBox(b)&&(s?function(e,t){let n=e.matrixWorld,a=e.geometry,s=a.attributes.instanceStart,l=a.attributes.instanceEnd,u=Math.min(a.instanceCount,s.count);for(let a=0;a<u;a++){v.start.fromBufferAttribute(s,a),v.end.fromBufferAttribute(l,a),v.applyMatrix4(n);let u=new o.Pq0,c=new o.Pq0;r.distanceSqToSegment(v.start,v.end,c,u),c.distanceTo(u)<.5*i&&t.push({point:c,pointOnLine:u,distance:r.origin.distanceTo(c),object:e,face:null,faceIndex:a,uv:null,uv1:null})}}(this,t):function(e,t,n){let a=t.projectionMatrix,s=e.material.resolution,l=e.matrixWorld,u=e.geometry,c=u.attributes.instanceStart,b=u.attributes.instanceEnd,w=Math.min(u.instanceCount,c.count),g=-t.near;r.at(1,p),p.w=1,p.applyMatrix4(t.matrixWorldInverse),p.applyMatrix4(a),p.multiplyScalar(1/p.w),p.x*=s.x/2,p.y*=s.y/2,p.z=0,h.copy(p),m.multiplyMatrices(t.matrixWorldInverse,l);for(let t=0;t<w;t++){if(d.fromBufferAttribute(c,t),f.fromBufferAttribute(b,t),d.w=1,f.w=1,d.applyMatrix4(m),f.applyMatrix4(m),d.z>g&&f.z>g)continue;if(d.z>g){let e=d.z-f.z,t=(d.z-g)/e;d.lerp(f,t)}else if(f.z>g){let e=f.z-d.z,t=(f.z-g)/e;f.lerp(d,t)}d.applyMatrix4(a),f.applyMatrix4(a),d.multiplyScalar(1/d.w),f.multiplyScalar(1/f.w),d.x*=s.x/2,d.y*=s.y/2,f.x*=s.x/2,f.y*=s.y/2,v.start.copy(d),v.start.z=0,v.end.copy(f),v.end.z=0;let u=v.closestPointToPointParameter(h,!0);v.at(u,y);let p=o.cj9.lerp(d.z,f.z,u),w=p>=-1&&p<=1,S=h.distanceTo(y)<.5*i;if(w&&S){v.start.fromBufferAttribute(c,t),v.end.fromBufferAttribute(b,t),v.start.applyMatrix4(l),v.end.applyMatrix4(l);let i=new o.Pq0,a=new o.Pq0;r.distanceSqToSegment(v.start,v.end,a,i),n.push({point:a,pointOnLine:i,distance:r.origin.distanceTo(a),object:e,face:null,faceIndex:t,uv:null,uv1:null})}}}(this,l,t))}}onBeforeRender(e){let t=this.material.uniforms;t&&t.resolution&&(e.getViewport(l),this.material.uniforms.resolution.value.set(l.z,l.w))}}var E=n(5516);class _ extends x{constructor(e=new E.v,t=new s.G({color:0xffffff*Math.random()})){super(e,t),this.isLine2=!0,this.type="Line2"}}},9113:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0});var n={bindSnapshot:function(){return u},createAsyncLocalStorage:function(){return s},createSnapshot:function(){return c},getOrCreateGlobalAsyncLocalStorage:function(){return l}};for(var r in n)Object.defineProperty(t,r,{enumerable:!0,get:n[r]});let i=Error("Invariant: AsyncLocalStorage accessed in runtime where it is not available");class o{disable(){throw i}getStore(){}run(){throw i}exit(){throw i}enterWith(){throw i}static bind(e){return e}}let a="u">typeof globalThis&&globalThis.AsyncLocalStorage;function s(){return a?new a:new o}function l(e){let t=Symbol.for(`@next/${e}@16.4.0`),n=globalThis;return n[t]??=s()}function u(e){return a?a.bind(e):o.bind(e)}function c(){return a?a.snapshot():function(e,...t){return e(...t)}}}}]);