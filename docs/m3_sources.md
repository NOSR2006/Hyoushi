# M3 依据来源登记表

> 由 `tools/gen_m3_sources.py --write` 生成（**抓取当日：2026-10-07**，sha256 对 HTTP 响应体的
> 原始字节计算）。`tools/probes/m3tokens.py` 第 10 关**不联网**地钉住这份表：清单里的每一份
> 1 级文件都在表里、每份都带 64 位 sha256、三条链的前缀与 `Design system version: v0.192`
> 都在。依据顺序与裁决规则见 `AGENTS.md` 的「依据顺序」一节。

**镜像**：material-web 与 Flutter 走 jsDelivr（`cdn.jsdelivr.net/gh/...`），androidx 走
`ghproxy.net` 代理的 `raw.githubusercontent.com`（本机直连取不到）。androidx 与 Flutter 是
**分支型**来源，哈希只代表抓取当日；material-web 那份带版本戳 `v0.192`，是唯一可长期钉住的。

## 0 级｜生成器（能重算的绝不抄）

- `material-color-utilities==0.2.6` —— 颜色不是抄来的，是 `tools/gen_m3_tokens.py` 现算的（种子 `#3e63dd`、TONALSPOT、
  contrast 0.0，即 Flutter `ColorScheme.fromSeed` 的默认档 = 规范基线），冻结成
  `tools/m3_tokens.json`。
- 复算：`tools/probes/m3tokens.py PART 1-2` 用**同一个库**把 46 个角色 × 两套外观重算一遍、逐格比回来。

## 1 级｜数值权威：material-web 自动生成的设计系统导出

- 前缀 `https://cdn.jsdelivr.net/gh/material-components/material-web@main/tokens/versions/v0_192/`
- 每份文件开头逐字：`!!! THIS FILE WAS AUTOMATICALLY GENERATED !!!`、`!!! DO NOT MODIFY IT
  BY HAND !!!`，以及
  - `Design system display name: Google Material 3`
  - `Design system version: v0.192`
  - `User-configured context group "Audience": "3P"`
  - `"Platform": "Web"`
  - `"Scheme": "Dynamic"`
- **只认这一层**。同一仓库 `tokens/` 下**非 versioned** 的文件是 Material Web Components 的
  适配层（`validate.values(... $new-tokens ...)` 会自己加 token、改 token 名），**不算依据**；
  `tokens/v0_192/*.scss` 那批 130 B 存根只是 `@forward` 转发。

| 文件 | 字节 | sha256 | 我们引用的 token |
|---|---|---|---|
| `_md-comp-list.scss` | 12504 | `a32100dc4ff0565c58e3748f912c3e50ad666dedc1ac2e03d1fd4831f31aabe0` | `list-item-one-line-container-height`、`list-item-two-line-container-height`、`list-item-three-line-container-height`、`list-item-leading-image-width`、`list-item-leading-avatar-size`、`list-item-leading-icon-size`、`list-item-leading-space`、`list-item-trailing-space`、`list-item-label-text-font`、`list-item-supporting-text-font` |
| `_md-comp-switch.scss` | 6786 | `d1ea6d345157b729e529af21c13edd47004f0cf0184ca8d885032f27fbe68697` | `track-width`、`track-height`、`state-layer-size` |
| `_md-comp-filled-button.scss` | 4336 | `15542bd5ba06432cd747f6a21abb604435f3bd177b2c49c559f840857694df23` | `container-height`、`container-shape`、`label-text-font`、`with-icon-icon-size`、`disabled-container-opacity`、`disabled-label-text-opacity` |
| `_md-comp-outlined-button.scss` | 4031 | `de55b292d7a7f861f9b3c0affd94ff82b05b20d51eb653cd6a0b3eddcdc7fcd3` | `container-height`、`container-shape`、`label-text-font` |
| `_md-comp-outlined-text-field.scss` | 9040 | `2c8063c2b8d60055e03ba29b13e126d6e7d2e679a3079e38ce2323346ffba666` | `input-text-font`、`input-text-size`、`input-text-line-height`、`outline-width`、`focus-outline-width`、`leading-icon-size`、`trailing-icon-size` |
| `_md-comp-dialog.scss` | 5644 | `d6382d5fb185db5380a467e302308259168ae9b0d95fe7f737d133321dc7376f` | `container-color`、`container-elevation`、`container-shape`、`headline-font`、`headline-size`、`supporting-text-font`、`supporting-text-size`、`action-label-text-color`、`action-label-text-font` |
| `_md-comp-data-table.scss` | 4294 | `9949a164d8fcd7c9cf267c35cda6a25da8dc94ee943834457bad2adc0fa9f36b` | `header-container-height`、`row-item-container-height`、`header-headline-font`、`row-item-label-text-font`、`row-item-outline-width`、`row-item-outline-color`、`outline-width`、`outline-color`、`header-container-color`、`row-item-selected-container-color`、`row-item-unselected-hover-state-layer-color`、`row-item-unselected-hover-state-layer-opacity`、`row-item-selected-hover-state-layer-color`、`row-item-selected-hover-state-layer-opacity` |
| `_md-comp-navigation-rail.scss` | 5174 | `4fb6691a2adc9410547be4d819746ec7f864a6c389673186995f5c0f01cce590` | `container-width` |
| `_md-comp-top-app-bar-small.scss` | 2695 | `71bb2b97ada3ec4f561b6dfc1f7614bb4afce48c1ccdc4696544877f406d663a` | `container-height`、`container-color`、`container-elevation`、`headline-font` |
| `_md-comp-divider.scss` | 720 | `de302f3e66ae847f5aff5669154404ecc8a1770bd66dc04b2a631f38fa62d2fe` | `color`、`thickness` |
| `_md-comp-plain-tooltip.scss` | 2097 | `483098391d74c47bf70bc8d1d718973292388dc68f73bebbd9d023b1cd09b227` | `container-color`、`container-shape`、`supporting-text-font` |
| `_md-comp-filled-icon-button.scss` | 3652 | `c92e990c415b7808e7e83541e6a113b729b1b418132148e68d0196540edd138b` | `container-shape`、`icon-size`、`disabled-icon-opacity`、`disabled-container-opacity` |
| `_md-comp-menu.scss` | 1456 | `d32db0c611db7f7b8d58e33e4316e0ee424079354ce17086279fbbb9ef8451cc` | `container-color`、`container-elevation`、`container-shape` |
| `_md-comp-snackbar.scss` | 5684 | `ff2b6238ac175b71d385fd66808d79c8c70af29c24c5bdbf2e476e486d9250a8` | `container-color`、`container-elevation`、`container-shape`、`supporting-text-font`、`action-label-text-font` |
| `_md-comp-elevated-card.scss` | 2496 | `e37530710e66b98ca03f0347c49c85782664bebc10f30d4fd20591f12be45cc7` | `container-color`、`container-elevation`、`container-shape` |
| `_md-comp-assist-chip.scss` | 5335 | `d49ab8c83bb0ea02d108b0ca0e7e955a7dc966c7bd8659cefe3a3b79c7f1f59b` | `container-height`、`container-shape`、`label-text-font`、`with-icon-icon-size` |
| `_md-sys-shape.scss` | 1364 | `2ffa44f85591cde7f501aafb8e26c422d341b1eae56b3e2fab7ab6034a3ee6eb` | `corner-extra-small`、`corner-small`、`corner-medium`、`corner-large`、`corner-extra-large`、`corner-full` |
| `_md-sys-elevation.scss` | 798 | `658319c50ce8f33f08d567493dfe52106e9ef177f43b4d6a38526ee339e24972` | `level0`、`level1`、`level2`、`level3`、`level4`、`level5` |
| `_md-sys-state.scss` | 781 | `d410dd5d47c1bc25b25b6fa82901bdf8d555360cbd35716bc73ed8d6a61ea6f8` | `hover-state-layer-opacity`、`focus-state-layer-opacity`、`pressed-state-layer-opacity`、`dragged-state-layer-opacity` |
| `_md-sys-typescale.scss` | 15230 | `7c8cbd48c99465a6924eff73d7809c764f528a81933206d548e1a88b33dbe8d9` | `body-large-size`、`body-medium-size`、`label-large-size`、`title-large-size`、`headline-small-size` |

## 2 级｜意图权威

- `https://m3.material.io/` —— 讲的是**为什么**（组件语义、用法、无障碍），不是数值。它是单页
  应用，正文抓不到；唯一实抓成功的是 cards 规格表（`OFFICIAL_CARD` 的 16/8）。**抓不到就记
  「未取证」，不许凭印象补数**。数值上与 1 级冲突时听 1 级，并在 `DEVIATIONS` 登记。

## 3 级｜旁证与平台补位

### 3a androidx Compose Material3（**旁证**；取它的值必须与 1 级相符，对不上就不采）

- 前缀 `https://raw.githubusercontent.com/androidx/androidx/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/`（`Chip.kt`/`Menu.kt`/`Button.kt` 在 `material3/` 根目录，不在 `tokens/`）
- 有些文件带 `// VERSION:` 戳（见下表），没有戳的只能按分支记。**androidx 含 Material 3
  Expressive 的增量**（本项目只走最纯正的 M3，一律不采）。
- **1 级没定义、只有它给的**算「3a 补位」（注释里要点明是哪一条）：输入框容器高 56
  （`OutlinedTextFieldTokens.ContainerHeight` —— 1 级的 `_md-comp-outlined-text-field.scss`
  整个文件都没有 56）、开关四色与手柄几何（1 级只给 `track-width` 52 / `track-height` 32 /
  `state-layer-size` 40）。
- **与 1 级不符的一律不采**，只作分歧记录留在表里：`StateTokens.kt` 写 focus/pressed 各 0.1，
  1 级 `_md-sys-state.scss` 写 0.12 ⇒ 跟 1 级（用户 m19222 定）。

| 文件 | 字节 | sha256 | VERSION | 用途 |
|---|---|---|---|---|
| `tokens/StateTokens.kt` | 935 | `f9bddb282a3ca50e0c05bda6b5aa713441f885e3fe16866bfb44cee42059552f` | v0_210 | 状态层**分歧记录**：它写 focus/pressed 各 0.1，与 1 级 0.12 不符 ⇒ 不采 |
| `tokens/SwitchTokens.kt` | 6336 | `02e6a40ac3b295782066f7d6de65badab2070240f56f7eb03d482cc0b6f32c85` | v0_210 | 开关四色与手柄几何 |
| `tokens/OutlinedTextFieldTokens.kt` | 6597 | `04ffa7424f96b8ad0e82dfcf2bfbeb122a509c5b26478633ce56077018863fa6` | v0_103 | 输入框 56 / 描边 1 / 聚焦 2 / 图标 24 |
| `tokens/TypeScaleTokens.kt` | 16942 | `7ca6378374d78da8a1091d2ee4a4c228f70d0daef65dfd51c18b58f7d9679ba4` | v0_103 | 15 档字阶（tracking 三处与 Web 导出不同） |
| `tokens/AssistChipTokens.kt` | 3917 | `8ea69b2b3996905eb6b447347746d143877ca588887077af80d84c2c77381fa5` | 7_0_1 | chip 32 / 图标 18 |
| `tokens/FilterChipTokens.kt` | 7843 | `6a718caa30f5ce889889bb20eae01f9fa9bf2400c36c1c8d8856b1dedc95a61a` | 7_0_1 | flat 三条：未选中描边 outline_variant、选中 0、选中底 secondary_container |
| `Chip.kt` | 202811 | `d3f1c95d15522e08a2b8222956ff0503c346f97aab670741ab8b7aedcfe538d9` | （无戳） | chip 内边距 8 / 横向间距 8 |
| `tokens/ProgressIndicatorTokens.kt` | 1279 | `6e576f0947414aee1bcf35bd291c52facc5dbcedf8ab80947aea14dd05ab2bdc` | v0_4_0 | 轨道 secondary_container / 活动段 primary / 全 4.0 |
| `tokens/LinearProgressIndicatorTokens.kt` | 1657 | `43c6931eb19698ce8bc1b520882bae4d08e1bb1f7228a054664fac4090858f71` | v0_7_0 | 线性进度条 4.0 |
| `tokens/ShapeTokens.kt` | 2944 | `02178111f81c7f03135cc7157040fa903180e212fd52b8f686b4304080efb5a3` | 14_1_0 | 4/8/12/16/28/full |
| `tokens/ElevationTokens.kt` | 1243 | `b0613cc2c1e30fb62da126f82f5870f7231e3cf4117f36132e466e1827de0a3c` | v0_103 | 0/1/3/6/8/12 |
| `tokens/AppBarSmallTokens.kt` | 1064 | `c27b71c51b688338bd800c10a49ee08bf5942a23fd9dbf04827ff6c6d51846a7` | 14_0_0 | 顶栏 64 |
| `tokens/ListTokens.kt` | 12620 | `bc69140567eaa2780a9d945ef7b7e299e92214b9434a9b566708ac46e31bc463` | 29.0.0 | 列表 56/72/88 与 leading 图标 24 |
| `Menu.kt` | 103403 | `f6fe29552c15e79a2a102d65fc450bb60c34816cbda0580e98c8539588ce2938` | （无戳） | 菜单项 48 与 ItemLabelTextFont = BodyLarge |
| `tokens/ElevatedCardTokens.kt` | 2031 | `d5640de0fc99b0c9bd883c3282c30a15cac66af5b6d3877ef7ee2dc3a8289e3d` | v0_210 | elevated 卡三件套 |
| `tokens/SnackbarTokens.kt` | 2453 | `b2db9c11b3f3ec0069cfbae6a62afd7a949fcc8b90185c2a821fc0e023735a29` | v0_103 | snackbar 三件套 |
| `tokens/PlainTooltipTokens.kt` | 1084 | `e8bd62f82c4be1a560aa6508877b66b74629b0d1ab57a6eb6bbd82fd16600754` | （无戳） | tooltip 三件套 |
| `tokens/DividerTokens.kt` | 954 | `3e4729399cfdc37d2f44ea9ffc2336ac7c80e8479ed012f5f9e52d1f9c7f7826` | v0_117 | 分隔线 outline_variant / 1dp |
| `Button.kt` | 89599 | `4d18a20b7cbe4f670ba83dcc460e9be8415dda3ab509af93dcff97a80f99882e` | （无戳） | 按钮 40 / corner-full / label-large |

### 3b Flutter（只在 M3 **没有定义**的地方用）

- `https://cdn.jsdelivr.net/gh/flutter/flutter@master/`（material 组件）与
  `https://cdn.jsdelivr.net/gh/flutter/packages@main/`（`animations` 包 —— 它**不在**
  `flutter/flutter` 里，第一版引错了仓库、404 过一次）。
- 用它的每一处都必须在注释里写明「这是 Flutter 的选择，不是 M3 的规定」。

| 文件 | 字节 | sha256 | 用途 |
|---|---|---|---|
| `flutter/flutter@master/packages/flutter/lib/src/material/scrollbar.dart` | 15040 | `4f5a94586bc52086f4662e40129015c71a40b7f1aad3dc4b464aaf85abe940b0` | M3 没有滚动条组件：粗 8 / 半径 8（画在 8dp 上夹成 4） |
| `flutter/flutter@master/packages/flutter/lib/src/material/navigation_rail.dart` | 46825 | `d14bf880a99d70eb1d61e6e856d92d53322f27d937ec5fd5ccb0f92e818a4e2d` | 收起 80 / 展开 256（`_NavigationRailDefaultsM3`） |
| `flutter/flutter@master/packages/flutter/lib/src/material/data_table.dart` | 54032 | `aa1a11501ffa1f2d0dfdf2d76f57208b307e5492f84eac9893f7d92f4b5c428c` | 排序箭头格 18 |
| `flutter/flutter@master/packages/flutter/lib/src/material/filter_chip.dart` | 12986 | `3609e41968bbf8e2ca80ac5242376c8c11d50c89fec3c19e0949f198972582b2` | flat 未选中不铺底、选中描边透明 |
| `flutter/packages@main/packages/animations/lib/src/fade_through_transition.dart` | 9300 | `529d44deee81c001e03ae18361e83273cfa498c60f3a4d4d452d5d2794fe048a` | 换页 `_scaleIn` 0.92 与两拍曲线（`_inCurve` Cubic(0,0,0.2,1) / `_outCurve` Cubic(0.4,0,1,1)） |

## 4 级｜落地层

- Flet 1.0.3（`https://flet.dev/docs/`）+ **Flet MCP**（`get_api`/`list_controls`/`get_enum`/
  `search_enum_members`/`enum_has_member`/`find_icon`）—— 只决定「Flet 能怎么表达」，
  不决定「M3 要求什么」。

## 5 级｜本项目自身

- `tools/m3_theme.py`（令牌与组件主题）、`tools/m3_tokens.json`、`AGENTS.md`、`DEVIATIONS`
  —— 这是**结果**不是来源：与高级别冲突时改代码，不改来源。

