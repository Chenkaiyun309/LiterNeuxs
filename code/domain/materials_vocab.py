#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
materials_vocab.py

材料科学词表库（Materials Science Vocabulary Library）

本模块提供：
1. 材料科学领域术语白名单（MATERIALS_SCIENCE_VOCAB）——用于正向识别材料科学相关内容
2. 非材料科学停用词黑名单（NON_MATERIALS_STOPWORDS）——用于过滤与材料科学无关的词语
3. 过滤函数：
   - filter_tokens_by_materials_relevance(): 过滤词元，剔除非材料科学词语
   - is_materials_science_related(): 判断文本是否与材料科学相关
   - filter_papers_by_materials_relevance(): 按材料科学相关性过滤文献记录

使用方式：
    from materials_vocab import (
        NON_MATERIALS_STOPWORDS,
        filter_tokens_by_materials_relevance,
        is_materials_science_related,
        filter_papers_by_materials_relevance,
    )
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# ============================================================
# 1. 材料科学领域术语白名单
#    用于正向判断文本/词语是否属于材料科学范畴
# ============================================================

# 材料类型
MATERIAL_TYPES = {
    # 金属与合金
    "alloy", "alloys", "metal", "metals", "steel", "stainless", "titanium",
    "aluminum", "aluminium", "copper", "nickel", "cobalt", "iron", "magnesium",
    "zinc", "tungsten", "molybdenum", "chromium", "vanadium", "niobium",
    "tantalum", "zirconium", "hafnium", "rhenium", "platinum", "gold", "silver",
    "palladium", "rhodium", "iridium", "osmium", "ruthenium", "tin", "lead",
    "bismuth", "antimony", "lithium", "sodium", "potassium", "calcium",
    "scandium", "yttrium", "lanthanum", "cerium", "neodymium", "samarium",
    "gadolinium", "dysprosium", "terbium", "holmium", "erbium", "ytterbium",
    "lutetium", "praseodymium", "promethium", "europium", "thulium", "actinium",
    "thorium", "uranium", "beryllium", "manganese", "gallium", "indium",
    "thallium", "germanium", "cadmium", "mercury", "titanium", "superelastic",
    "superalloy", "superalloys", "intermetallic", "intermetallics", "heusler",
    "shape-memory", "nitinol", "amorphous", "metallic", "glassy", "bulk",
    "high-entropy", "high-entropy alloy", "refractory", "cast", "wrought",
    "galvanized", "anodized", "electroplated", "powder", "sintered",
    # 钛合金
    "tial", "ti6al4v", "ta15", "ta31", "beta-ti", "alpha-ti", "ti22al25nb",
    "ticrti", "cucoti", "cucrti",
    # 陶瓷
    "ceramic", "ceramics", "alumina", "zirconia", "silica", "titania",
    "silicon", "carbide", "nitride", "oxide", "boride", "silicide",
    "siC", "si3n4", "al2o3", "zro2", "tio2", "bioactive", "bioceramic",
    "piezoelectric", "ferroelectric", "dielectric", "perovskite", "spinel",
    "garnet", "fluorite", "rutile", "anatase", "brookite",
    # 聚合物与高分子
    "polymer", "polymers", "polymerization", "polyethylene", "polypropylene",
    "polystyrene", "polyurethane", "epoxy", "resin", "resins", "rubber",
    "elastomer", "elastomers", "copolymer", "copolymers", "hydrogel",
    "hydrogels", "biopolymer", "biopolymers", "thermoplastic", "thermoset",
    "crosslinked", "crosslinking", "graft", "blend", "blends", "composite",
    "composites", "nanocomposite", "nanocomposites", "biopolymer",
    "conducting", "polymer", "membrane", "membranes", "film", "films",
    "coating", "coatings",
    # 复合材料
    "composite", "composites", "laminate", "laminates", "fiber", "fibers",
    "fibre", "fibres", "matrix", "reinforcement", "reinforced", "cfrp",
    "gfrp", "prepreg", "sandwich", "honeycomb", "particulate", "whisker",
    "whiskers", "nanotube", "nanotubes", "graphene", "fullerene",
    "buckypaper",
    # 半导体与电子材料
    "semiconductor", "semiconductors", "silicon", "germanium", "gaas",
    "gan", "inp", "sic", "ga2o3", "zno", "mos2", "wse2", "transition",
    "dichalcogenide", "photovoltaic", "photovoltaics", "led", "oled",
    "transistor", "transistors", "diode", "diodes", "capacitor",
    "capacitors", "resistor", "resistors", "electrode", "electrodes",
    "cathode", "anode", "electrolyte", "electrolytes", "battery",
    "batteries", "supercapacitor", "supercapacitors", "li-ion", "sodium-ion",
    "solid-state", "perovskite",
    # 纳米材料
    "nanoparticle", "nanoparticles", "nanocrystal", "nanocrystals",
    "nanowire", "nanowires", "nanorod", "nanorods", "nanosheet",
    "nanosheets", "nanotube", "nanotubes", "quantum", "dot", "dots",
    "nanostructure", "nanostructures", "nanomaterial", "nanomaterials",
    "mesoporous", "microporous", "nanoporous", "self-assembled",
    "self-assembly",
    # 生物质材料 / 生物医用材料
    "biomaterial", "biomaterials", "biodegradable", "bioactive",
    "biocompatible", "implant", "implants", "scaffold", "scaffolds",
    "hydroxyapatite", "collagen", "chitosan", "alginate", "cellulose",
    "starch", "gelatin", "fibrin", "silk", "chitin",
    # 功能材料
    "magnetic", "ferromagnetic", "paramagnetic", "diamagnetic",
    "antiferromagnetic", "ferrimagnetic", "magnetocaloric",
    "magnetostrictive", "piezoelectric", "pyroelectric", "ferroelectric",
    "electrostrictive", "magnetoresistance", "gmr", "cmr", "superconducting",
    "superconductor", "superconductors", "thermoelectric", "thermoelectrics",
    "photocatalytic", "photocatalysis", "electrocatalytic",
    "electrocatalysis", "catalyst", "catalysts", "catalysis", "sorbent",
    "sorbents", "adsorbent", "adsorbents",
    # 建筑材料 / 能源材料
    "cement", "concrete", "mortar", "plaster", "gypsum", "asphalt",
    "bitumen", "geopolymer", "fuel", "cell", "cells", "solar", "wind",
    "hydrogen", "storage", "electrode",
}

# 材料性能
MATERIAL_PROPERTIES = {
    "strength", "ductility", "hardness", "toughness", "stiffness",
    "modulus", "elasticity", "plasticity", "yield", "tensile", "compressive",
    "flexural", "shear", "fatigue", "creep", "fracture", "toughening",
    "brittle", "ductile", "elastic", "plastic", "viscoelastic",
    "superplastic", "anisotropic", "isotropic", "orthotropic",
    "corrosion", "oxidation", "wear", "erosion", "abrasion", "friction",
    "tribological", "passivation", "degradation", "durability",
    "thermal", "conductivity", "resistivity", "expansion", "diffusivity",
    "stability", "insulation", "conducting", "semiconducting",
    "dielectric", "magnetic", "optical", "transparency", "reflectivity",
    "absorption", "luminescence", "fluorescence", "phosphorescence",
    "photoconductivity", "barrier", "permeability", "porosity", "density",
    "biocompatibility", "bioactivity", "cytotoxicity", "hemocompatibility",
    "osseointegration", "biodegradability",
    # 中文性能词
    "强度", "塑性", "韧性", "硬度", "刚性", "弹性", "屈服", "抗拉", "抗压",
    "抗弯", "剪切", "疲劳", "蠕变", "断裂", "脆性", "延性", "延展性",
    "各向异性", "各向同性", "腐蚀", "氧化", "磨损", "摩擦", "钝化",
    "降解", "耐久", "导热", "导电", "电阻", "膨胀", "扩散", "稳定性",
    "绝缘", "介电", "磁性", "光学", "透过率", "反射率", "吸收",
    "发光", "荧光", "磷光", "光电导", "渗透", "孔隙", "密度",
    "生物相容", "生物活性", "细胞毒性", "血液相容", "骨结合", "可降解",
}

# 表征与测试方法
CHARACTERIZATION_METHODS = {
    "xrd", "x-ray", "diffraction", "sem", "tem", "ebsd", "eds", "edx",
    "wds", "xps", "aes", "afm", "stm", "ftir", "raman", "uv-vis",
    "nmr", "esr", "epr", "mossbauer", "dsc", "tga", "dta", "dma",
    "tensile", "testing", "nanoindentation", "hardness", "microscopy",
    "microscope", "spectroscopy", "spectrometer", "calorimetry",
    "diffractometer", "tomography", "microtomography", "ct",
    "neutron", "synchrotron", "saxs", "waxs", "gisaxs", "lebail",
    "rietveld", "pole", "texture", "grain", "morphology", "topography",
    "fractography", "electrochemical", "impedance", "potentiodynamic",
    "polarization", "cyclic", "voltammetry", "chronoamperometry",
    "wear", "scratch", "indentation", "impact", "charpy", "izod",
    # 中文方法词
    "衍射", "电镜", "扫描", "透射", "能谱", "光谱", "红外", "拉曼",
    "核磁", "量热", "热重", "拉伸", "压缩", "弯曲", "硬度测试",
    "纳米压痕", "显微", "形貌", "断口", "电化学", "阻抗", "极化",
    "循环伏安", "磨损", "冲击",
}

# 加工与制备方法
PROCESSING_METHODS = {
    "annealing", "annealed", "quenching", "quenched", "tempering",
    "tempered", "aging", "aged", "precipitation", "solution", "treatment",
    "heat", "normalizing", "spheroidizing", "recrystallization",
    "recovery", "grain", "refinement", "rolling", "forging", "extrusion",
    "drawing", "spinning", "casting", "solidification", "solidified",
    "sintering", "sintered", "powder", "metallurgy", "compaction",
    "hot", "isostatic", "pressing", "cold", "deformation", "strain",
    "strain", "rate", "work", "hardening", "cold-working", "warm",
    "additive", "manufacturing", "3d", "printing", "slm", "selective",
    "laser", "melting", "ebm", "electron", "beam", "lpbf", "ded",
    "directed", "energy", "deposition", "cladding", "welding", "welded",
    "brazing", "soldering", "joining", "bonding", "coating", "coated",
    "deposition", "cvd", "pvd", "sputtering", "evaporation", "plating",
    "anodizing", "anodized", "electrodeposition", "electroplating",
    "sol-gel", "spin", "dip", "spray", "thermal", "barrier",
    "thermomechanical", "tmp", "thermomechanical", "processing",
    "equal-channel", "angular", "pressing", "ecap", "hpt",
    "high-pressure", "torsion", "severe", "plastic", "deformation",
    "spd", "accumulative", "roll", "bonding", "arb", "cyclic",
    "extrusion", "cyclic",
    # 中文加工词
    "退火", "淬火", "回火", "时效", "析出", "固溶", "热处理", "正火",
    "球化", "再结晶", "回复", "晶粒细化", "轧制", "锻造", "挤压",
    "拉拔", "旋压", "铸造", "凝固", "烧结", "粉末冶金", "压制",
    "热等静压", "冷加工", "变形", "应变", "加工硬化", "增材制造",
    "3d打印", "选区激光熔化", "电子束熔化", "激光粉末床熔融",
    "定向能量沉积", "熔覆", "焊接", "钎焊", "连接", "键合",
    "涂层", "沉积", "化学气相沉积", "物理气相沉积", "溅射",
    "蒸发", "电镀", "阳极氧化", "电沉积", "溶胶凝胶", "旋涂",
    "浸涂", "喷涂", "热障涂层", "热机械", "等径角挤压",
    "高压扭转", "剧烈塑性变形", "累积叠轧",
}

# 微观结构
MICROSTRUCTURE_TERMS = {
    "microstructure", "microstructures", "grain", "grains", "grain",
    "boundary", "boundaries", "phase", "phases", "precipitate",
    "precipitates", "precipitation", "inclusion", "inclusions",
    "defect", "defects", "dislocation", "dislocations", "vacancy",
    "vacancies", "interstitial", "interstitials", "stacking", "fault",
    "twin", "twins", "twinning", "slip", "slip", "system", "texture",
    "preferred", "orientation", "recrystallization", "nucleation",
    "growth", "coarsening", "dissolution", "segregation", "ordering",
    "short-range", "long-range", "amorphous", "crystalline",
    "polycrystalline", "single-crystal", "single", "epitaxial",
    "epitaxy", "nanocrystalline", "ultrafine", "columnar", "equiaxed",
    "dendritic", "dendrite", "dendrites", "eutectic", "eutectoid",
    "peritectic", "martensite", "martensitic", "bainite", "bainitic",
    "pearlite", "pearlitic", "ferrite", "ferritic", "austenite",
    "austenitic", "cementite", "widmanstatten", "supersaturated",
    "solid", "solution", "intermetallic", "intermetallics", "lattice",
    "crystal", "crystalline", "unit", "cell", "parameter", "spacing",
    "interplanar", "interatomic", "bonding", "covalent", "ionic",
    "metallic", "van", "der", "waals", "hydrogen", "bond",
    # 中文结构词
    "微观结构", "晶粒", "晶界", "相", "析出", "析出物", "夹杂物",
    "缺陷", "位错", "空位", "间隙", "层错", "孪晶", "孪生", "滑移",
    "织构", "择优取向", "再结晶", "形核", "长大", "粗化", "溶解",
    "偏聚", "有序", "短程有序", "长程有序", "非晶", "晶体",
    "多晶", "单晶", "外延", "纳米晶", "超细", "柱状", "等轴",
    "枝晶", "共晶", "共析", "包晶", "马氏体", "贝氏体", "珠光体",
    "铁素体", "奥氏体", "渗碳体", "魏氏", "过饱和", "固溶体",
    "金属间化合物", "晶格", "晶胞", "晶格常数", "间距", "键合",
    "共价", "离子", "金属键", "氢键",
}

# 汇总白名单
MATERIALS_SCIENCE_VOCAB = (
    MATERIAL_TYPES
    | MATERIAL_PROPERTIES
    | CHARACTERIZATION_METHODS
    | PROCESSING_METHODS
    | MICROSTRUCTURE_TERMS
)

# 知识图谱专用术语规则。它们与上方专业术语词表保持在同一模块中，
# 供 Web 图谱、趋势扩展和后续词表维护共用。
KNOWLEDGE_MATERIAL_PATTERNS = [
    ("Ti alloy", r"\bTi[-\s]?alloy|titanium alloy|钛合金"),
    ("Nb alloy", r"\bNb[-\s]?alloy|niobium alloy|铌合金"),
    ("Pt alloy", r"\bPt[-\s]?alloy|platinum alloy|铂合金"),
    ("Ni alloy", r"\bNi[-\s]?alloy|nickel alloy|镍合金"),
    ("Al alloy", r"\bAl[-\s]?alloy|aluminum alloy|aluminium alloy|铝合金"),
    ("steel", r"\bsteel\b|stainless steel|不锈钢|钢"),
    ("refractory alloy", r"refractory alloy|refractory high entropy alloy|难熔合金"),
    ("Ti-6Al-4V", r"Ti[-\s]?6Al[-\s]?4V"),
    ("β-Ti", r"(?:β|beta)[-\s]?Ti|metastable\s+β|亚稳β|β钛"),
    ("α+β Ti", r"(?:α|alpha)\s*\+\s*(?:β|beta)|α\s*\+\s*β"),
    ("TA15", r"\bTA15\b"),
    ("TA31", r"\bTA31\b"),
    ("Ti-22Al-25Nb", r"Ti[-\s]?22Al[-\s]?25Nb"),
    ("Cu-Cr-Ti", r"Cu[-\s]?Cr[-\s]?Ti"),
    ("Cu-Co-Ti", r"Cu[-\s]?Co[-\s]?Ti"),
    ("high entropy alloy", r"high[-\s]?entropy alloy|高熵合金"),
    ("CFRP/Ti stack", r"CFRP\s*/\s*Ti|CFRP[-\s]?Ti"),
    ("biomedical Ti", r"biomedical|implant|osseointegration|生物医用|植入"),
]

KNOWLEDGE_PROPERTY_PATTERNS = [
    ("strength", r"\bstrength\b|yield strength|tensile strength|ultimate strength|抗拉强度|屈服强度|强度"),
    ("ductility", r"\bductility\b|elongation|plasticity|延展性|塑性|伸长率"),
    ("hardness", r"\bhardness\b|microhardness|显微硬度|硬度"),
    ("corrosion resistance", r"corrosion resistance|corrosion-resistant|耐蚀|抗腐蚀|耐腐蚀"),
    ("wear resistance", r"wear resistance|wear-resistant|耐磨|抗磨损"),
    ("fatigue resistance", r"fatigue resistance|fatigue life|疲劳性能|抗疲劳"),
    ("fracture toughness", r"fracture toughness|断裂韧性|韧性"),
    ("electrical conductivity", r"electrical conductivity|conductivity|导电性|电导率"),
    ("thermal stability", r"thermal stability|thermal resistance|热稳定性|耐热"),
    ("elastic modulus", r"elastic modulus|Young'?s modulus|modulus|弹性模量"),
    ("biocompatibility", r"biocompatib|bioactivity|biological response|生物相容性|生物活性"),
]

KNOWLEDGE_METHOD_PATTERNS = [
    ("CALPHAD", r"\bCALPHAD\b"),
    ("ANN", r"\bANN\b|artificial neural network|人工神经网络"),
    ("machine learning", r"machine learning|机器学习|data[-\s]?driven|数据驱动"),
    ("SLM", r"\bSLM\b|selective laser melting|选区激光熔化"),
    ("additive manufacturing", r"additive manufacturing|增材制造|3D printing|laser powder bed fusion"),
    ("EBSD", r"\bEBSD\b|electron backscatter"),
    ("TEM", r"\bTEM\b|transmission electron microscopy|透射电镜"),
    ("SEM", r"\bSEM\b|scanning electron microscopy|扫描电镜"),
    ("XRD", r"\bXRD\b|x-ray diffraction|X射线衍射"),
    ("aging", r"\baging\b|aged\b|时效"),
    ("annealing", r"\banneal(?:ing|ed)?\b|退火"),
    ("thermomechanical processing", r"thermomechanical|热机械"),
    ("oxygen charging", r"oxygen[-\s]?charging|氧(?:含量)?梯度|充氧"),
    ("surface coating", r"coating|涂层|surface modification|表面改性"),
]

KNOWLEDGE_KEYWORD_PATTERNS = [
    ("additive manufacturing", r"additive manufacturing|增材制造|3D printing|laser powder bed fusion"),
    ("fuel cell", r"fuel cells?|燃料电池"),
    ("oxygen reduction reaction", r"oxygen reduction reaction|\bORR\b|氧还原"),
    ("hydrogen evolution reaction", r"hydrogen evolution reaction|\bHER\b|析氢"),
    ("strength-ductility", r"strength[-–\s]?ductility|强度.*延展|塑性"),
    ("microstructure", r"microstructure|微观结构|组织"),
    ("grain refinement", r"grain refinement|晶粒细化"),
    ("precipitation", r"precipitat|析出"),
    ("deformation mechanism", r"deformation mechanism|变形机制"),
    ("welding", r"weld|焊接"),
    ("drilling", r"drilling|钻孔"),
    ("laser processing", r"laser|激光"),
]

KNOWLEDGE_GRAPH_PATTERN_GROUPS = {
    "material": KNOWLEDGE_MATERIAL_PATTERNS,
    "property": KNOWLEDGE_PROPERTY_PATTERNS,
    "method": KNOWLEDGE_METHOD_PATTERNS,
    "keyword": KNOWLEDGE_KEYWORD_PATTERNS,
}

# 趋势对比词表比“材料相关性”更严格：
# 只保留可解释研究方向差异的术语，排除单独出现时语义过泛或跨领域歧义很强的词。
TREND_TERM_EXCLUSIONS = {
    "active", "activity", "activities", "additive", "advanced", "alloy", "alloys",
    "barrier", "beam", "bond", "bonding", "bulk", "cell", "cells",
    "cold", "conducting", "cyclic", "density", "dot", "dots",
    "dynamic", "effect", "effects", "energy", "environmental", "film",
    "films", "fuel", "growth", "heat", "hot", "impact", "large", "matrix",
    "graft", "grafts", "manufacturing", "metal", "metals", "parameters",
    "particles", "part", "parts", "phase", "phases",
    "powder", "process", "processing", "quantum", "rate", "resistance",
    "refractory", "selective", "severe", "single", "sites", "solid", "solution", "spin", "strategy",
    "strategies", "surface", "system", "systems", "testing", "treatment",
    "treatments", "unit", "work",
    "材料", "合金", "结构", "性能", "方向", "趋势", "过程", "体系", "方法",
}

TREND_MATERIAL_HINTS = {
    "alloy", "ceramic", "composite", "polymer", "coating", "catalyst",
    "catalysts", "electrocatalyst", "electrocatalysts", "photocatalyst",
    "photocatalysts", "membrane", "membranes", "implant", "implants",
    "scaffold", "scaffolds", "nanoparticle", "nanoparticles",
    "nanowire", "nanowires", "nanotube", "nanotubes", "oxide", "nitride",
    "carbide", "boride", "silicide",
}

# ============================================================
# 2. 非材料科学停用词黑名单
#    用于过滤与材料科学无关的词语
# ============================================================

NON_MATERIALS_STOPWORDS = {
    # 通用学术词
    "study", "studied", "studies", "research", "researcher", "researchers",
    "paper", "papers", "article", "articles", "review", "reviews",
    "report", "reports", "result", "results", "finding", "findings",
    "conclusion", "conclusions", "summary", "overview", "introduction",
    "background", "objective", "objectives", "aim", "aims", "goal", "goals",
    "purpose", "purposes", "method", "methods", "methodology",
    "methodologies", "approach", "approaches", "framework", "frameworks",
    "model", "models", "modeling", "modelling", "simulation", "simulations",
    "analysis", "analyses", "analytical", "calculate", "calculated",
    "calculation", "calculations", "compute", "computed", "computation",
    "data", "dataset", "datasets", "database", "databases", "sample",
    "samples", "sampling", "experiment", "experiments", "experimental",
    "test", "tests", "testing", "tested", "measurement", "measurements",
    "measure", "measured", "observe", "observed", "observation",
    "observations", "demonstrate", "demonstrated", "show", "shown", "shows",
    "showed", "indicate", "indicated", "indicates", "suggest", "suggested",
    "suggests", "reveal", "revealed", "reveals", "confirm", "confirmed",
    "confirms", "prove", "proved", "proven", "proves", "establish",
    "established", "identify", "identified", "identifies", "determine",
    "determined", "determines", "investigate", "investigated",
    "investigates", "investigation", "investigations", "examine",
    "examined", "examines", "explore", "explored", "explores",
    "evaluate", "evaluated", "evaluates", "evaluation", "assess",
    "assessed", "assesses", "assessment", "compare", "compared",
    "compares", "comparison", "comparisons", "discuss", "discussed",
    "discusses", "discussion", "describe", "described", "describes",
    "description", "present", "presented", "presents", "propose",
    "proposed", "proposes", "proposal", "develop", "developed",
    "develops", "development", "design", "designed", "designs",
    "optimize", "optimized", "optimizes", "optimization", "improve",
    "improved", "improves", "improvement", "enhance", "enhanced",
    "enhances", "enhancement", "increase", "increased", "increases",
    "decrease", "decreased", "decreases", "reduce", "reduced", "reduces",
    "reduction", "achieve", "achieved", "achieves", "obtain", "obtained",
    "obtains", "acquire", "acquired", "acquires", "collect", "collected",
    "collects", "record", "recorded", "records", "monitor", "monitored",
    "monitors", "track", "tracked", "tracks", "follow", "followed",
    "follows", "support", "supported", "supports", "provide", "provided",
    "provides", "offer", "offered", "offers", "contribute", "contributed",
    "contributes", "contribution", "lead", "led", "leads", "cause",
    "caused", "causes", "result", "resulted", "results", "produce",
    "produced", "produces", "generate", "generated", "generates",
    "create", "created", "creates", "form", "formed", "forms",
    # 通用形容词/副词
    "different", "similar", "various", "several", "many", "much", "more",
    "most", "less", "least", "few", "little", "small", "large", "big",
    "great", "greater", "greatest", "high", "higher", "highest", "low",
    "lower", "lowest", "strong", "stronger", "strongest", "weak", "weaker",
    "weakest", "good", "better", "best", "bad", "worse", "worst", "new",
    "novel", "recent", "current", "previous", "prior", "early", "late",
    "later", "future", "past", "present", "modern", "traditional",
    "conventional", "advanced", "emerging", "promising", "potential",
    "possible", "impossible", "likely", "unlikely", "certain", "uncertain",
    "clear", "unclear", "obvious", "significant", "insignificant",
    "important", "unimportant", "critical", "crucial", "essential",
    "fundamental", "primary", "secondary", "major", "minor", "main",
    "key", "central", "core", "basic", "general", "specific", "particular",
    "special", "common", "rare", "unique", "typical", "atypical",
    "normal", "abnormal", "standard", "nonstandard", "regular",
    "irregular", "uniform", "nonuniform", "homogeneous", "heterogeneous",
    "consistent", "inconsistent", "stable", "unstable", "successful",
    "unsuccessful", "effective", "ineffective", "efficient", "inefficient",
    "adequate", "inadequate", "appropriate", "inappropriate", "suitable",
    "unsuitable", "feasible", "infeasible", "available", "unavailable",
    "accessible", "inaccessible", "visible", "invisible", "detectable",
    "undetectable", "measurable", "immeasurable", "noticeable",
    "negligible", "remarkable", "considerable", "substantial",
    "significant", "dramatic", "gradual", "sudden", "rapid", "slow",
    "fast", "quick", "brief", "extended", "prolonged", "continuous",
    "discontinuous", "intermittent", "periodic", "aperiodic", "cyclic",
    "acyclic", "reversible", "irreversible", "repeatable",
    "reproducible",
    # 通用动词
    "using", "used", "use", "uses", "based", "according", "depending",
    "related", "associated", "linked", "connected", "coupled", "combined",
    "mixed", "separated", "isolated", "extracted", "purified",
    "synthesized", "prepared", "fabricated", "manufactured", "assembled",
    "constructed", "built", "made", "done", "performed", "carried",
    "conducted", "executed", "implemented", "applied", "employed",
    "utilized", "adopted", "selected", "chosen", "picked", "taken",
    "given", "provided", "supplied", "delivered", "transferred",
    "transported", "moved", "shifted", "changed", "modified", "altered",
    "adjusted", "adapted", "converted", "transformed", "translated",
    "transmitted", "propagated", "diffused", "dispersed", "distributed",
    "spread", "scattered", "concentrated", "accumulated", "deposited",
    "absorbed", "adsorbed", "released", "emitted", "discharged",
    "removed", "eliminated", "reduced", "increased", "decreased",
    "raised", "lowered", "elevated", "depressed", "expanded",
    "contracted", "stretched", "compressed", "bent", "folded", "twisted",
    "rotated", "turned", "oriented", "aligned", "arranged", "ordered",
    "organized", "structured", "patterned", "shaped", "formed",
    # 代词/介词/连词
    "their", "theirs", "them", "they", "these", "those", "this", "that",
    "which", "who", "whom", "whose", "what", "where", "when", "why",
    "how", "whether", "if", "then", "else", "while", "whereas",
    "although", "though", "despite", "because", "since", "until",
    "unless", "before", "after", "during", "through", "throughout",
    "between", "among", "within", "without", "inside", "outside",
    "above", "below", "over", "under", "upon", "onto", "into", "onto",
    "from", "to", "toward", "towards", "along", "across", "around",
    "about", "against", "beside", "besides", "beyond", "behind",
    "between", "amongst", "amidst", "via", "by", "with", "within",
    "for", "of", "in", "on", "at", "as", "be", "been", "being", "is",
    "are", "was", "were", "do", "does", "did", "have", "has", "had",
    "will", "would", "shall", "should", "can", "could", "may", "might",
    "must", "ought", "need", "dare", "not", "no", "nor", "or", "and",
    "but", "so", "yet", "both", "either", "neither", "each", "every",
    "all", "any", "some", "such", "same", "other", "another", "one",
    "two", "three", "first", "second", "third", "last", "next",
    "former", "latter",
    # 期刊/出版相关
    "journal", "journals", "proceedings", "conference", "conferences",
    "symposium", "workshop", "meeting", "volume", "issue", "page",
    "pages", "figure", "figures", "table", "tables", "scheme", "schemes",
    "equation", "equations", "formula", "formulas", "formulae",
    "chapter", "chapters", "section", "sections", "appendix",
    "supplementary", "supporting", "information", "doi", "isbn", "issn",
    "copyright", "license", "licensed", "published", "publication",
    "publisher", "author", "authors", "editor", "editors", "reviewer",
    "reviewers", "referee", "referees", "corresponding", "affiliation",
    "affiliations", "department", "university", "institute", "institutes",
    "laboratory", "lab", "labs", "center", "centre", "centers",
    "school", "college", "academy", "society", "societies", "association",
    "associations", "organization", "organisations", "organizations",
    "foundation", "foundations", "council", "agency", "agencies",
    # 作者姓氏（常见中文姓氏拼音）
    "zhang", "wang", "chen", "liu", "yang", "liang", "li", "huang",
    "zhao", "wu", "zhou", "xu", "sun", "ma", "zhu", "hu", "guo", "he",
    "lin", "luo", "gao", "lu", "zheng", "liang", "song", "tang", "han",
    "feng", "deng", "cao", "peng", "zeng", "xie", "yu", "ye", "luo",
    "pan", "yuan", "jiang", "tan", "xiao", "jin", "qiu", "shi", "duan",
    "wei", "shen", "mu", "ni", "du", "ding", "ren", "shen", "yao",
    "lu", "su", "lu", "wei", "qian", "lei", "bai", "long", "duan",
    # 非材料科学领域词
    "patient", "patients", "clinical", "clinic", "diagnosis", "diagnostic",
    "diagnose", "diagnosed", "treatment", "treatments", "treat", "treated",
    "therapy", "therapeutic", "therapeutics", "drug", "drugs", "dosage",
    "dose", "dosing", "medication", "medications", "medicine", "medicines",
    "disease", "diseases", "disorder", "disorders", "syndrome", "syndromes",
    "symptom", "symptoms", "infection", "infections", "inflammatory",
    "inflammation", "immune", "immunity", "immunization", "vaccine",
    "vaccines", "vaccination", "antibody", "antibodies", "antigen",
    "antigens", "cellular", "cell", "cells", "cellular", "tissue",
    "tissues", "organ", "organs", "blood", "plasma", "serum", "urine",
    "saliva", "biopsy", "biopsies", "surgery", "surgical", "surgeon",
    "surgeons", "hospital", "hospitals", "nursing", "nurse", "nurses",
    "epidemiology", "epidemiological", "public", "health", "mortality",
    "morbidity", "incidence", "prevalence", "survival", "survivor",
    "survivors", "death", "deaths", "malignant", "benign", "tumor",
    "tumors", "tumour", "tumours", "cancer", "cancers", "carcinoma",
    "carcinomas", "sarcoma", "sarcomas", "lymphoma", "lymphomas",
    "leukemia", "leukaemia", "melanoma", "melanomas",
    # 社会科学/经济/管理
    "economic", "economics", "economy", "economies", "market", "markets",
    "marketing", "finance", "financial", "business", "businesses",
    "management", "manager", "managers", "policy", "policies",
    "governance", "government", "political", "politics", "social",
    "societal", "society", "societies", "cultural", "culture", "cultures",
    "psychological", "psychology", "behavioral", "behavior", "behaviour",
    "behaviours", "educational", "education", "educational", "learning",
    "teaching", "teacher", "teachers", "student", "students", "school",
    "schools", "curriculum", "pedagogy", "historical", "history",
    "philosophical", "philosophy", "ethical", "ethics", "moral", "morals",
    "legal", "law", "laws", "regulation", "regulations", "regulatory",
    # 计算机科学（非材料计算）
    "software", "hardware", "program", "programs", "programming",
    "programmer", "programmers", "algorithm", "algorithms", "code",
    "codes", "coding", "database", "databases", "server", "servers",
    "client", "clients", "network", "networks", "networking", "internet",
    "web", "website", "websites", "online", "offline", "digital",
    "virtual", "cloud", "computing", "computer", "computers", "machine",
    "machines", "robot", "robots", "robotics", "artificial",
    "intelligence", "deep", "neural", "network", "networks", "learning",
    "training", "trained", "classifier", "classifiers", "classification",
    "regression", "clustering", "segmentation", "recognition",
    "detection", "tracking", "prediction", "predict", "predicted",
    "predicts", "forecast", "forecasting", "forecasted",
    # 通用中文词
    "主要", "研究", "方法", "文献", "材料", "性能", "结构", "合金",
    "当前", "通过", "进行", "采用", "利用", "使用", "基于", "根据",
    "关于", "对于", "由于", "鉴于", "随着", "尽管", "虽然", "但是",
    "然而", "因此", "所以", "因为", "如果", "假设", "条件", "情况",
    "状态", "过程", "阶段", "时期", "时间", "空间", "区域", "范围",
    "方面", "方向", "领域", "学科", "专业", "课题", "项目", "计划",
    "目标", "任务", "要求", "标准", "规范", "准则", "原则", "规律",
    "现象", "特征", "特点", "特性", "属性", "本质", "内涵", "外延",
    "概念", "定义", "含义", "意义", "作用", "功能", "效果", "影响",
    "结果", "结论", "总结", "归纳", "概括", "描述", "说明", "解释",
    "阐述", "论述", "讨论", "分析", "比较", "对比", "评价", "评估",
    "预测", "展望", "趋势", "动向", "动态", "进展", "发展", "变化",
    "演变", "演化", "转化", "转变", "过渡", "迁移", "传播", "扩散",
    "本文", "本研究", "该项", "该研究", "上述", "下述", "其中",
    "此外", "另外", "同时", "随后", "然后", "最终", "最后", "首先",
    "其次", "再次", "另外", "此外", "而且", "并且", "以及", "或者",
    "还是", "不是", "不能", "不会", "没有", "无法", "可以", "能够",
    "应该", "需要", "必须", "可能", "也许", "大概", "大约", "左右",
    "上下", "以内", "以外", "以上", "以下", "之前", "之后", "之间",
    "之中", "之内", "之外", "前面", "后面", "上面", "下面", "里面",
    "外面", "旁边", "附近", "周围", "中间", "中心", "两端", "两侧",
}

# ============================================================
# 3. 过滤函数
# ============================================================

# 预编译正则：提取英文词元和中文词组
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-]{3,}|[\u4e00-\u9fff]{2,6}")


def _normalize_token(word: str) -> str:
    """将词元归一化：小写、去首尾连字符。"""
    return word.lower().strip("-").strip()


def extract_knowledge_graph_terms(text: str, auto_terms: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """
    从文本中抽取知识图谱节点术语。

    返回值为 (term, category) 列表，category 取值：
    material / property / method / keyword。
    """
    terms: dict[str, str] = {}
    for category in ("material", "property", "method", "keyword"):
        for label, pattern in KNOWLEDGE_GRAPH_PATTERN_GROUPS[category]:
            if re.search(pattern, text, flags=re.IGNORECASE):
                terms.setdefault(label, category)

    for raw_term in auto_terms or []:
        term = str(raw_term).strip()
        if term and term not in terms:
            terms[term] = "keyword"

    return list(terms.items())


def is_materials_science_term(term: str) -> bool:
    """
    判断单个词语是否与材料科学相关。

    判断逻辑：
    1. 归一化后命中材料科学白名单 -> True
    2. 归一化后命中非材料科学黑名单 -> False
    3. 包含材料科学关键词子串 -> True
    4. 默认 -> False（保守过滤，未识别的词视为无关）
    """
    word = _normalize_token(term)
    if not word or len(word) < 2:
        return False

    # 黑名单优先。部分词（cell、treatment 等）在材料短语中有意义，
    # 但单独出现时跨领域歧义过强，不能作为材料相关性的正证据。
    if word in NON_MATERIALS_STOPWORDS:
        return False

    # 命中白名单
    if word in MATERIALS_SCIENCE_VOCAB:
        return True

    # 子串匹配：检查是否包含材料科学关键词
    for vocab_term in MATERIALS_SCIENCE_VOCAB:
        if len(vocab_term) >= 4 and vocab_term in word:
            return True
        if len(word) >= 4 and word in vocab_term:
            return True

    # 中文词：如果包含材料科学中文词的任一字符组合，保守保留
    if re.search(r"[\u4e00-\u9fff]", word):
        for cn_term in MATERIAL_PROPERTIES | MICROSTRUCTURE_TERMS | PROCESSING_METHODS:
            if cn_term and re.search(r"[\u4e00-\u9fff]", cn_term):
                if cn_term in word or word in cn_term:
                    return True

    return False


def is_trend_comparison_term(term: str) -> bool:
    """
    判断单个词是否适合进入趋势对比。

    该函数故意比 is_materials_science_term() 更保守。趋势对比会直接影响
    “共同关键词/独有关键词”的解释，因此单独出现时过泛或跨领域歧义强的词
    不进入对比，即使它们在某些材料短语中可能有意义。
    """
    word = _normalize_token(term)
    if not word or len(word) < 4:
        return False
    if re.search(r"[\u4e00-\u9fff]", word) and (
        word.endswith(("的", "和", "与", "及", "或", "中", "为"))
        or any(marker in word for marker in ("有待", "本文", "研究"))
    ):
        return False
    if word in NON_MATERIALS_STOPWORDS or word in TREND_TERM_EXCLUSIONS:
        return False

    singular = word[:-1] if word.endswith("s") else word
    if singular in TREND_TERM_EXCLUSIONS:
        return False

    if word in MATERIALS_SCIENCE_VOCAB or singular in MATERIALS_SCIENCE_VOCAB:
        return True

    if any(hint in word for hint in TREND_MATERIAL_HINTS):
        return True

    # 常见合金/材料牌号：Ti-6Al-4V、Pt-alloy、Nb2O5、Zr-Nb、Al-Mg-Si-Ti 等。
    element_symbols = {"ti", "al", "nb", "pt", "ni", "cu", "fe", "zr", "ta", "mo", "v", "cr", "co", "mn", "mg", "zn", "pd", "si"}
    if "alloy" in word or any(kind in word for kind in ("oxide", "nitride", "carbide", "boride", "silicide")):
        return bool(re.search(r"(?:ti|al|nb|pt|ni|cu|fe|zr|ta|mo|v|cr|co|mn|mg|zn|pd|si)", word))
    if re.search(r"(?:ti|al|nb|pt|ni|cu|fe|zr|ta|mo|v|cr|co|mn|mg|zn|pd|si)[a-z]*\d", word):
        return True
    if "-" in word:
        parts = [part for part in word.split("-") if part]
        element_like = 0
        for part in parts:
            if part in element_symbols or re.fullmatch(r"(?:ti|al|nb|pt|ni|cu|fe|zr|ta|mo|v|cr|co|mn|mg|zn|pd|si)\d*[a-z]?\d*", part):
                element_like += 1
        if element_like >= 2 and element_like == len(parts):
            return True

    if re.search(r"[\u4e00-\u9fff]", word):
        for cn_term in MATERIAL_PROPERTIES | MICROSTRUCTURE_TERMS | PROCESSING_METHODS:
            if cn_term and re.search(r"[\u4e00-\u9fff]", cn_term):
                if word == cn_term:
                    return True

    return False


def filter_tokens_by_materials_relevance(
    tokens: Iterable[str],
    *,
    keep_unknown: bool = False,
) -> list[str]:
    """
    过滤词元列表，剔除与材料科学无关的词语。

    参数:
        tokens: 待过滤的词元列表
        keep_unknown: True 时保留无法判断的词；False 时剔除（默认）

    返回:
        过滤后的词元列表
    """
    result: list[str] = []
    for token in tokens:
        word = _normalize_token(token)
        if not word:
            continue
        if word in NON_MATERIALS_STOPWORDS:
            continue
        if word in MATERIALS_SCIENCE_VOCAB:
            result.append(token)
            continue
        # 子串匹配
        is_related = False
        for vocab_term in MATERIALS_SCIENCE_VOCAB:
            if len(vocab_term) >= 4 and vocab_term in word:
                is_related = True
                break
            if len(word) >= 4 and word in vocab_term:
                is_related = True
                break
        if is_related:
            result.append(token)
        elif keep_unknown:
            result.append(token)
    return result


def is_materials_science_related(
    text: str,
    *,
    min_score: int = 1,
) -> bool:
    """
    判断一段文本是否与材料科学相关。

    通过统计文本中材料科学术语的命中数来判断。
    命中数 >= min_score 则认为相关。

    参数:
        text: 待判断的文本
        min_score: 最少命中数（默认 1）

    返回:
        True 表示与材料科学相关
    """
    if not text:
        return False

    # 预处理：将 β/α 替换为可匹配形式
    cleaned = text.replace("β", " beta ").replace("α", " alpha ")
    tokens = _TOKEN_RE.findall(cleaned)

    score = 0
    for token in tokens:
        word = _normalize_token(token)
        if word in NON_MATERIALS_STOPWORDS:
            continue
        if word in MATERIALS_SCIENCE_VOCAB:
            score += 1
            if score >= min_score:
                return True

    # 子串匹配（对较长文本做一次额外检查）
    if score < min_score:
        text_lower = text.lower()
        for vocab_term in MATERIALS_SCIENCE_VOCAB:
            if vocab_term in NON_MATERIALS_STOPWORDS:
                continue
            if len(vocab_term) >= 5 and vocab_term in text_lower:
                score += 1
                if score >= min_score:
                    return True

    return score >= min_score


def filter_papers_by_materials_relevance(
    records: list[Any],
    *,
    text_fields: tuple[str, ...] = ("title", "abstract"),
    min_score: int = 1,
    logger: Any = None,
) -> list[Any]:
    """
    按材料科学相关性过滤文献记录。

    遍历每条记录的指定文本字段，判断是否与材料科学相关。
    不相关的记录将被剔除。

    参数:
        records: 文献记录列表（PaperRecord 或 dict）
        text_fields: 用于判断的文本字段名
        min_score: 最少命中数
        logger: 可选的日志回调

    返回:
        过滤后的记录列表
    """
    kept: list[Any] = []
    removed_count = 0

    for record in records:
        # 兼容 PaperRecord（属性访问）和 dict
        texts: list[str] = []
        for field in text_fields:
            if hasattr(record, field):
                texts.append(str(getattr(record, field, "") or ""))
            elif isinstance(record, dict):
                texts.append(str(record.get(field, "") or ""))

        combined_text = " ".join(texts)
        if is_materials_science_related(combined_text, min_score=min_score):
            kept.append(record)
        else:
            removed_count += 1

    if removed_count > 0 and logger:
        try:
            logger(f"[VocabFilter] 过滤掉 {removed_count} 条与材料科学无关的文献")
        except Exception:
            pass

    return kept


def get_vocab_stats() -> dict[str, int]:
    """返回词表库统计信息。"""
    return {
        "material_types": len(MATERIAL_TYPES),
        "material_properties": len(MATERIAL_PROPERTIES),
        "characterization_methods": len(CHARACTERIZATION_METHODS),
        "processing_methods": len(PROCESSING_METHODS),
        "microstructure_terms": len(MICROSTRUCTURE_TERMS),
        "total_whitelist": len(MATERIALS_SCIENCE_VOCAB),
        "total_blacklist": len(NON_MATERIALS_STOPWORDS),
    }
