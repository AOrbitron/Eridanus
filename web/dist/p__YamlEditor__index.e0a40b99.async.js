"use strict";(self.webpackChunkant_design_pro=self.webpackChunkant_design_pro||[]).push([[441],{28609:(function(Ue,B,i){var G=i(37810),g=i.n(G),J=i(26572),v=i.n(J),X=i(92990),E=i(60790),R=i(94686),L=["children","type","delay","duration","className","style","component"],q=function(o){var _=100;switch(o){case"top":return{hidden:{opacity:0,y:-_},visible:{opacity:1,y:0}};case"bottom":return{hidden:{opacity:0,y:_},visible:{opacity:1,y:0}};case"left":return{hidden:{opacity:0,x:-_},visible:{opacity:1,x:0}};case"right":return{hidden:{opacity:0,x:_},visible:{opacity:1,x:0}};case"scale":return{hidden:{opacity:0,scale:.8},visible:{opacity:1,scale:1}};default:return{hidden:{opacity:0},visible:{opacity:1}}}},P=function(o){var _=o.children,U=o.type,p=U===void 0?"right":U,O=o.delay,ne=O===void 0?0:O,I=o.duration,re=I===void 0?500:I,D=o.className,ae=o.style,F=o.component,W=F===void 0?"div":F,te=v()(o,L),x=X.Children.toArray(_),se=Array.isArray(p)?p[0]:p,T=q(se),ie=E.P[W]||(0,E.P)(W);return(0,R.jsx)(ie,g()(g()({className:D,style:ae},te),{},{children:x.map(function(w,K){var ue=(ne+K*100)/1e3,N=re/1e3;return(0,R.jsx)(E.P.div,{initial:T.hidden,animate:T.visible,transition:{delay:ue,duration:N,ease:"backOut"},children:w},w.key||K)})}))};B.A=P}),34923:(function(Ue,B,i){i.r(B);var G=i(76979),g=i.n(G),J=i(57704),v=i.n(J),X=i(37810),E=i.n(X),R=i(65788),L=i.n(R),q=i(98047),P=i.n(q),ee=i(55472),o=i.n(ee),_=i(92990),U=i(1644),p=i(15207),O=i(49472),ne=i(66348),I=i(94092),re=i(96676),D=i(49544),ae=i(12141),F=i(81889),W=i(81324),te=i(5918),x=i(94668),se=i(23247),T=i(64088),ie=i(90315),w=i(7436),K=i(40825),ue=i(24477),N=i(48063),k=i(747),j=i(7663),We=i(28609),n=i(94686),V=I.A.TextArea,Te=function(){var we=ae.Ay.useMessage(),he=o()(we,2),m=he[0],Ke=he[1],Ne=(0,j.useParams)(),b=Ne.fileName,ke=(0,j.useLocation)(),pe=ke.search,Ve=(0,_.useState)([]),fe=o()(Ve,2),Z=fe[0],ze=fe[1],$e=(0,_.useState)(""),ve=o()($e,2),M=ve[0],Ye=ve[1],He=(0,_.useState)({}),Ee=o()(He,2),A=Ee[0],le=Ee[1],Qe=(0,_.useState)(!1),ge=o()(Qe,2),z=ge[0],Pe=ge[1],Ge=(0,_.useState)(!1),be=o()(Ge,2),Je=be[0],ye=be[1],Xe=(0,_.useState)(!1),De=o()(Xe,2),qe=De[0],Ae=De[1],en=(0,_.useState)(""),Ce=o()(en,2),oe=Ce[0],nn=Ce[1],rn=(0,_.useState)([]),Le=o()(rn,2),xe=Le[0],je=Le[1],an=(0,_.useState)(!1),Me=o()(an,2),tn=Me[0],S=Me[1],sn=(0,_.useState)(!1),Oe=o()(sn,2),un=Oe[0],de=Oe[1],ln=(0,_.useState)(""),Ie=o()(ln,2),_e=Ie[0],ce=Ie[1],on=(0,_.useState)(""),Fe=o()(on,2),dn=Fe[0],_n=Fe[1],cn=(0,_.useState)([]),Ze=o()(cn,2),me=Ze[0],mn=Ze[1],hn=(0,_.useState)({}),Se=o()(hn,2),C=Se[0],$=Se[1],pn=function u(a){if(Array.isArray(a))return a.map(function(e){return typeof e=="string"&&!isNaN(Number(e))&&e.trim()!==""?Number(e):P()(e)==="object"&&e!==null?u(e):e});if(P()(a)==="object"&&a!==null){var r={};for(var l in a)a.hasOwnProperty(l)&&(r[l]=u(a[l]));return r}return a},fn=(function(){var u=L()(v()().mark(function a(){var r,l;return v()().wrap(function(t){for(;;)switch(t.prev=t.next){case 0:return t.prev=0,ye(!0),r=E()({},A),r.data&&(r.data=pn(r.data)),t.next=6,(0,k.x_)(M,r);case 6:l=t.sent,l.message?m.success("\u914D\u7F6E\u6587\u4EF6\u4FDD\u5B58\u6210\u529F"):m.error(l.error||"\u4FDD\u5B58\u5931\u8D25"),t.next=13;break;case 10:t.prev=10,t.t0=t.catch(0),m.error("\u4FDD\u5B58\u914D\u7F6E\u6587\u4EF6\u65F6\u51FA\u9519: "+t.t0);case 13:return t.prev=13,ye(!1),t.finish(13);case 16:case"end":return t.stop()}},a,null,[[0,10,13,16]])}));return function(){return u.apply(this,arguments)}})(),y=function(a,r){for(var l=a.split("."),e=E()({},A),t=e.data||e,s=0;s<l.length-1;s++){var h=l[s];if(h.includes("[")){var c=h.split("["),d=o()(c,2),f=d[0],Y=d[1],H=parseInt(Y.replace("]",""),10);t=t[f][H]}else t=t[h]}var Q=l[l.length-1];if(Q.includes("[")){var yn=Q.split("["),Re=o()(yn,2),Dn=Re[0],An=Re[1],Cn=parseInt(An.replace("]",""),10);t[Dn][Cn]=r}else t[Q]=r;le(e)},vn=function(a,r){_n(a),mn(r),ce(""),de(!0)},En=function(){if(!_e.trim()){m.warning("\u8BF7\u8F93\u5165\u8981\u6DFB\u52A0\u7684\u5185\u5BB9\uFF01");return}var a=_e.split(`
`).filter(function(l){return l.trim()!==""}),r=a.map(function(l){return me.length>0&&P()(me[0])==="object"?{}:l.trim()});y(dn,[].concat(g()(me),g()(r))),de(!1),ce(""),m.success("\u6210\u529F\u6DFB\u52A0 ".concat(r.length," \u9879"))},gn=function u(a,r){if(typeof a=="boolean")return(0,n.jsx)(T.A,{checked:a,checkedChildren:"\u5F00",unCheckedChildren:"\u5173",onChange:function(t){return y(r,t)}});if(typeof a=="string")return(0,n.jsx)(V,{value:a,onChange:function(t){return y(r,t.target.value)},autoSize:{minRows:1,maxRows:5}});if(typeof a=="number")return(0,n.jsx)(re.A,{type:"number",value:a,style:{width:"100%"},onChange:function(t){t==null||y(r,t)}});if(Array.isArray(a)){var l;return(0,n.jsxs)("div",{className:"array-container",children:[a.map(function(e,t){var s;return(0,n.jsxs)("div",{className:"array-item",children:[(0,n.jsx)(ne.A,{checked:((s=C[r])===null||s===void 0?void 0:s[t])||!1,onChange:function(c){var d=E()({},C);d[r]||(d[r]=Array(a.length).fill(!1)),d[r][t]=c.target.checked,$(d)}}),e===null?(0,n.jsx)(V,{value:e,onChange:function(c){var d=g()(a);d[t]=c.target.value,y(r,d)},autoSize:{minRows:1,maxRows:5}}):P()(e)==="object"?(0,n.jsx)("div",{className:"nested-object",style:{flex:1},children:Object.entries(e).map(function(h){var c=o()(h,2),d=c[0],f=c[1];return(0,n.jsxs)("div",{className:"object-item",children:[(0,n.jsxs)("strong",{children:[d,":"]}),(0,n.jsx)("div",{style:{marginLeft:"10px"},children:u(f,"".concat(r,"[").concat(t,"].").concat(d))})]},d)})}):(0,n.jsx)(V,{value:e,onChange:function(c){var d=g()(a);d[t]=c.target.value,y(r,d)},autoSize:{minRows:1,maxRows:5}})]},t)}),(0,n.jsxs)(x.A,{wrap:!0,children:[(0,n.jsx)(p.A,{type:"dashed",onClick:function(){var t,s=E()({},C),h=((t=C[r])===null||t===void 0?void 0:t.every(function(c){return c}))||!1;s[r]=Array(a.length).fill(!h),$(s)},children:(l=C[r])!==null&&l!==void 0&&l.every(function(e){return e})?"\u53D6\u6D88\u5168\u9009":"\u5168\u9009"}),(0,n.jsx)(W.A,{title:"\u786E\u8BA4\u5220\u9664\u5417\uFF1F",placement:"topRight",onConfirm:function(){var t,s=((t=C[r])===null||t===void 0?void 0:t.map(function(d,f){return d?f:-1}).filter(function(d){return d!==-1}))||[];if(a.length-s.length<1){m.warning("\u81F3\u5C11\u9700\u8981\u4FDD\u7559\u4E00\u9879");return}if(s.length===0){m.warning("\u8BF7\u5148\u9009\u62E9\u8981\u5220\u9664\u7684\u9879");return}var h=a.filter(function(d,f){return!s.includes(f)});y(r,h);var c=E()({},C);c[r]=Array(h.length).fill(!1),$(c),m.success("\u6210\u529F\u5220\u9664 ".concat(s.length," \u9879"))},okText:"\u662F",cancelText:"\u5426",children:(0,n.jsxs)(p.A,{type:"dashed",danger:!0,children:[(0,n.jsx)(ie.A,{}),"\u5220\u9664\u9009\u4E2D"]})}),(0,n.jsx)(p.A,{type:"dashed",icon:(0,n.jsx)(K.A,{}),onClick:function(){var t=P()(a[0])==="object"?{}:"";y(r,[].concat(g()(a),[t]))},children:"\u6DFB\u52A0\u4E00\u9879"}),(0,n.jsx)(p.A,{type:"dashed",icon:(0,n.jsx)(ue.A,{}),onClick:function(){vn(r,a)},children:"\u6279\u91CF\u6DFB\u52A0"})]})]})}return null},Pn=function u(a){var r=arguments.length>1&&arguments[1]!==void 0?arguments[1]:{},l=arguments.length>2&&arguments[2]!==void 0?arguments[2]:{},e=arguments.length>3&&arguments[3]!==void 0?arguments[3]:"",t=arguments.length>4&&arguments[4]!==void 0?arguments[4]:0,s=l[e]||Object.keys(a);return(0,n.jsx)(D.A,{dataSource:s,bordered:!1,split:!1,renderItem:function(c){var d=a[c],f=e?"".concat(e,".").concat(c):c,Y=r[f],H=d!==null&&P()(d)==="object"&&!Array.isArray(d);return(0,n.jsx)(D.A.Item,{className:"yaml-item",id:"yaml-item-".concat(f),style:{"--yaml-depth":t},children:(0,n.jsxs)(O.A,{style:{padding:0},className:"yaml-content",children:[(0,n.jsxs)("div",{className:"key-container".concat(H?" yaml-key-header yaml-key-header-sticky":""),children:[(0,n.jsxs)("strong",{style:{fontSize:"1.2rem"},children:[c,":"]}),Y&&(0,n.jsx)("span",{style:{textIndent:"1em",opacity:.8,overflow:"visible",textOverflow:"unset",whiteSpace:"normal",display:"block",maxWidth:"100%"},className:"comment",dangerouslySetInnerHTML:{__html:Y.replace(/((?:https?:\/\/)?(?:(?:[a-z0-9]?(?:[a-z0-9\-]{1,61}[a-z0-9])?\.[^\.|\s])+[a-z\.]*[a-z]+|(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3})(?::\d{1,5})*[a-z0-9.,_\/~#&=;%+?\-\\(\\)]*)/gi,'<a href="$&" target="_blank" style="word-break: break-all;">$&</a>')}})]}),e==="help_menu"&&c==="content"?(0,n.jsx)(p.A,{type:"primary",onClick:function(){j.history.push("/menuEditor")},children:"\u524D\u5F80\u83DC\u5355\u7F16\u8F91\u5668\u4FEE\u6539"}):H?(0,n.jsx)("div",{className:"nested-object",children:u(d,r,l,f,t+1)}):gn(d,f)]})})}})};(0,_.useEffect)(function(){var u=new AbortController,a=(function(){var r=L()(v()().mark(function l(){var e;return v()().wrap(function(s){for(;;)switch(s.prev=s.next){case 0:return s.prev=0,s.next=3,(0,k.v4)({signal:u.signal,skipErrorHandler:!0});case 3:if(e=s.sent,!u.signal.aborted){s.next=6;break}return s.abrupt("return");case 6:Array.isArray(e==null?void 0:e.files)?ze(e.files):m.error("\u914D\u7F6E\u6587\u4EF6\u5217\u8868\u52A0\u8F7D\u5931\u8D25"),s.next=12;break;case 9:s.prev=9,s.t0=s.catch(0),u.signal.aborted||m.error("\u83B7\u53D6\u6587\u4EF6\u5217\u8868\u65F6\u51FA\u9519: "+s.t0);case 12:case"end":return s.stop()}},l,null,[[0,9]])}));return function(){return r.apply(this,arguments)}})();return a(),function(){return u.abort()}},[]),(0,_.useEffect)(function(){if(Z.length){if(!b||!Z.includes(b)){j.history.replace("/configEditor/".concat(encodeURIComponent(Z[0])));return}var u=new AbortController;Ye(b),le({}),$({}),Pe(!0);var a=(function(){var r=L()(v()().mark(function l(){var e;return v()().wrap(function(s){for(;;)switch(s.prev=s.next){case 0:return s.prev=0,s.next=3,(0,k.Y3)(b,{signal:u.signal,skipErrorHandler:!0});case 3:if(e=s.sent,!u.signal.aborted){s.next=6;break}return s.abrupt("return");case 6:e?(le(e),e.error&&m.error("\u9519\u8BEF\uFF1A".concat(e.error))):m.error("\u914D\u7F6E\u6587\u4EF6\u52A0\u8F7D\u5931\u8D25"),s.next=12;break;case 9:s.prev=9,s.t0=s.catch(0),u.signal.aborted||m.error("\u914D\u7F6E\u6587\u4EF6\u52A0\u8F7D\u51FA\u9519: "+s.t0);case 12:return s.prev=12,u.signal.aborted||Pe(!1),s.finish(12);case 15:case"end":return s.stop()}},l,null,[[0,9,12,15]])}));return function(){return r.apply(this,arguments)}})();return a(),function(){return u.abort()}}},[b,Z]),(0,_.useEffect)(function(){var u=new URLSearchParams(pe).get("path");if(!(!u||z||M!==b)){var a=window.requestAnimationFrame(function(){var r;(r=document.getElementById("yaml-item-".concat(u)))===null||r===void 0||r.scrollIntoView({behavior:"smooth",block:"center"})});return function(){return window.cancelAnimationFrame(a)}}},[pe,z,M,b]);var Be=(function(){var u=L()(v()().mark(function a(){var r;return v()().wrap(function(e){for(;;)switch(e.prev=e.next){case 0:if(oe.trim()){e.next=3;break}return m.warning("\u8BF7\u5148\u8F93\u5165\u8981\u641C\u7D22\u7684\u5185\u5BB9"),e.abrupt("return");case 3:return e.prev=3,Ae(!0),e.next=7,(0,k.Es)(oe.trim());case 7:r=e.sent,r.results?(je(r.results),S(!0)):r.error?m.error(r.error):(je([]),S(!0),m.info("\u672A\u627E\u5230\u5339\u914D\u9879")),e.next=14;break;case 11:e.prev=11,e.t0=e.catch(3),m.error("\u641C\u7D22\u65F6\u51FA\u9519: "+e.t0);case 14:return e.prev=14,Ae(!1),e.finish(14);case 17:case"end":return e.stop()}},a,null,[[3,11,14,17]])}));return function(){return u.apply(this,arguments)}})(),bn=function(){return(0,n.jsx)(D.A,{dataSource:xe,renderItem:function(r){return(0,n.jsxs)(D.A.Item,{children:[(0,n.jsx)(D.A.Item.Meta,{title:(0,n.jsxs)("div",{children:["\u8DEF\u5F84\uFF1A",r.path]}),description:(0,n.jsxs)("div",{children:["\u6587\u4EF6\uFF1A",r.file]})}),(0,n.jsx)(p.A,{type:"primary",onClick:function(){if(M!==r.file)j.history.push("/configEditor/".concat(encodeURIComponent(r.file),"?").concat(new URLSearchParams({path:r.path})));else{var e=document.getElementById("yaml-item-".concat(r.path));e?e.scrollIntoView({behavior:"smooth",block:"center"}):m.error("\u672A\u627E\u5230\u5BF9\u5E94\u4F4D\u7F6E")}S(!1)},children:"\u8DF3\u8F6C"})]},r.path)}})};return(0,n.jsxs)(se.A,{spinning:z,size:"large",children:[Ke,(0,n.jsx)(U.A,{offsetTop:60,children:(0,n.jsx)("div",{className:"file-controls",children:(0,n.jsxs)(x.A,{wrap:!0,direction:"horizontal",style:{borderRadius:8,backdropFilter:"blur(8px)",padding:10,boxShadow:"0 0 10px rgba(112, 112, 112, 0.63)",width:"100%"},children:[(0,n.jsx)(te.A,{style:{width:"320px"},value:M||void 0,placeholder:"\u9009\u62E9\u6587\u4EF6",onChange:function(a){j.history.push("/configEditor/".concat(encodeURIComponent(a))),window.scrollTo({top:0,behavior:"smooth"})},suffixIcon:(0,n.jsx)(w.A,{}),options:Z.map(function(u){return{value:u,label:u}})}),(0,n.jsx)(p.A,{type:"primary",onClick:fn,loading:Je,disabled:z||!A.data||M!==b,children:"\u4FDD\u5B58\u914D\u7F6E"}),(0,n.jsxs)(p.A,{type:"primary",onClick:function(){return S(!0)},children:[(0,n.jsx)(N.A,{}),"\u641C\u7D22\u914D\u7F6E\u9879"]})]})})}),(0,n.jsx)(We.A,{type:"bottom",delay:100,children:(0,n.jsx)(O.A,{style:{padding:0},children:(0,n.jsxs)("div",{className:"yaml-editor",children:[(0,n.jsx)("div",{className:"editor-content",children:A.data&&Pn(A.data,A.comments,A.order)}),(0,n.jsx)(F.A,{title:"\u6279\u91CF\u6DFB\u52A0",open:un,onOk:En,onCancel:function(){return de(!1)},width:600,okText:"\u6DFB\u52A0",cancelText:"\u53D6\u6D88",children:(0,n.jsx)(V,{value:_e,onChange:function(a){return ce(a.target.value)},placeholder:"\u8BF7\u8F93\u5165\u8981\u6DFB\u52A0\u7684\u6570\u636E\uFF0C\u56DE\u8F66\u6362\u884C\uFF0C\u6BCF\u884C\u4E00\u9879",autoSize:{minRows:5,maxRows:20},style:{width:"100%"}})}),(0,n.jsx)(F.A,{title:"\u641C\u7D22\u914D\u7F6E\u9879",open:tn,onCancel:function(){return S(!1)},width:800,footer:null,children:(0,n.jsxs)(x.A,{direction:"vertical",style:{width:"100%"},children:[(0,n.jsxs)(x.A,{children:[(0,n.jsx)(I.A,{prefix:(0,n.jsx)(N.A,{}),placeholder:"\u641C\u7D22\u914D\u7F6E\u9879...",value:oe,onChange:function(a){return nn(a.target.value)},onPressEnter:Be,style:{width:"100%"}}),(0,n.jsx)(p.A,{type:"primary",onClick:Be,loading:qe,children:"\u641C\u7D22"})]}),(0,n.jsx)("div",{children:"\u63D0\u793A\uFF1A\u641C\u7D22\u8303\u56F4\u5305\u62EC\u5176\u5B83\u914D\u7F6E\u6587\u4EF6\uFF0C\u82E5\u5BF9\u5F53\u524D\u914D\u7F6E\u6587\u4EF6\u6709\u4FEE\u6539\uFF0C\u8BF7\u5148\u4FDD\u5B58\u540E\u518D\u8DF3\u8F6C\u3002"}),(0,n.jsx)("div",{style:{marginTop:"20px"},children:xe.length>0?bn():(0,n.jsx)("p",{children:"\u672A\u627E\u5230\u5339\u914D\u9879"})})]})}),(0,n.jsx)("style",{children:`
        .yaml-editor {
          --yaml-heading-top: 132px;
          --yaml-heading-height: 42px;
          // padding: 20px;
        }
        .file-controls {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
          display: flex;
          gap: 5px;
          padding: 5px;
        }
        .yaml-item {
          // border: 1px solid #e8e8e8;
          // padding: 5px;
          // margin-bottom: 10px;
          border-radius: 5px;
          align-items: flex-start;
          padding: 0;
        }
        .yaml-content {
          width: 100%;
        }
        /* \u6BCF\u4E2A\u5B57\u6BB5\u662F\u5D4C\u5957\u5728\u5916\u5C42\u73BB\u7483\u5361\u5185\u7684 Card\uFF1A\u7F6E\u4E3A\u900F\u660E\uFF0C\u907F\u514D\u591A\u5C42\u534A\u900F\u660E\u53E0\u52A0\u53C8\u53D8\u56DE\u7EAF\u767D */
        .yaml-content.ant-card {
          background: transparent !important;
          box-shadow: none !important;
          border: none !important;
          -webkit-backdrop-filter: none !important;
          backdrop-filter: none !important;
        }
        .key-container {
          margin-bottom: 8px;
        }
        /* Each YAML key behaves like an IDE code block heading while its value is visible. */
        .yaml-key-header {
          box-sizing: border-box;
          min-height: var(--yaml-heading-height);
          margin: 0 -16px 12px;
          padding: 9px 16px 8px;
          display: flex;
          align-items: baseline;
          gap: 10px;
          border-top: 1px solid var(--app-border, rgba(98, 116, 216, 0.2));
          border-bottom: 1px solid var(--app-border, rgba(98, 116, 216, 0.2));
          border-left: 3px solid color-mix(in srgb, #6274d8 72%, transparent);
          border-radius: 6px;
          background: color-mix(in srgb, var(--app-surface, #fff) 94%, #6274d8 6%);
          color: var(--app-text, inherit);
          box-shadow: 0 2px 8px rgba(30, 36, 60, 0.08);
        }
        .yaml-key-header-sticky {
          position: sticky;
          top: calc(var(--yaml-heading-top) + (var(--yaml-depth, 0) * var(--yaml-heading-height)));
          z-index: calc(20 - var(--yaml-depth, 0));
        }
        .yaml-key-header strong {
          flex: 0 0 auto;
          color: var(--app-text, inherit);
          font-weight: 700;
        }
        .yaml-key-header .comment {
          min-width: 0;
          color: var(--app-text, inherit);
        }
        .comment {
          margin-left: 8px;
        }
        .nested-object {
          margin-left: 20px;
          padding-left: 14px;
          border-left: 1px solid var(--app-border, rgba(98, 116, 216, 0.2));
        }
        .array-container {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .array-item {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        @media (max-width: 767px) {
          .yaml-editor {
            --yaml-heading-top: 178px;
          }
          .yaml-key-header {
            margin-left: -12px;
            margin-right: -12px;
            padding-left: 12px;
            padding-right: 12px;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .yaml-key-header {
            scroll-behavior: auto;
          }
        }
      `})]})},"a")})]})};B.default=Te})}]);
