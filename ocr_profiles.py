"""Explicit local OCR profiles; baseline remains available for comparison."""


def create_ocr(profile='bounded960_cpu2'):
    from rapidocr import RapidOCR
    params = {}
    if profile in ('bounded960','bounded1280','bounded960_cpu2'):
        params = {'Det.limit_type':'max', 'Det.limit_side_len':int(profile.split('_')[0][7:]),
                  'Global.use_cls':False}
        if profile.endswith('_cpu2'):
            params.update({'EngineConfig.onnxruntime.intra_op_num_threads':2,
                           'EngineConfig.onnxruntime.inter_op_num_threads':1})
    elif profile == 'mobile_en':
        from rapidocr import OCRVersion, ModelType, LangRec
        params = {'Det.ocr_version':OCRVersion.PPOCRV4, 'Det.model_type':ModelType.MOBILE,
                  'Rec.ocr_version':OCRVersion.PPOCRV4, 'Rec.model_type':ModelType.MOBILE,
                  'Rec.lang_type':LangRec.EN, 'Det.limit_type':'max',
                  'Det.limit_side_len':960, 'Global.use_cls':False}
    elif profile != 'baseline':
        raise ValueError('Unknown OCR profile')
    return RapidOCR(params=params)
