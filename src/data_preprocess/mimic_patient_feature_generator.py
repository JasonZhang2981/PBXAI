import csv
import os
from itertools import islice
import datetime
import re


def main():
    data_root = os.path.abspath('../../resource/raw_data/mimic')
    mapping_root = os.path.abspath('../../resource/mapping_file/mimic')
    save_root = os.path.abspath('../../resource/cache/mimic')

    diagnosis_path = os.path.join(data_root, 'DIAGNOSES_ICD.csv')
    admission_path = os.path.join(data_root, 'ADMISSIONS.csv')
    lab_test_path = os.path.join(data_root, 'LABEVENTS.csv')
    medicine_path = os.path.join(data_root, 'PRESCRIPTIONS.csv')
    vital_sign_path = os.path.join(data_root, 'CHARTEVENTS.csv')
    patient_path = os.path.join(data_root, 'PATIENTS.csv')
    code_name_path = os.path.join(data_root, 'D_LABITEMS.csv')
    operation_path = os.path.join(data_root, 'PROCEDURES_ICD.csv')
    diagnosis_mapping_path = os.path.join(mapping_root, 'DIAGNOSIS.csv')
    medicine_mapping_path = os.path.join(mapping_root, 'MEDICINE_NAME_MAP.csv')
    operation_mapping_path = os.path.join(mapping_root, 'OPERATION_MAP.csv')

    cardiac_ope_name_set = {'PCI', 'CABG', '瓣膜手术', '除颤器', '心脏再同步化治疗', '起搏器'}

    visit_dict = get_admissions(admission_path, save_root, read_from_cache=False)
    print('visit dict loaded')
    age_sex_dict = get_sex_age(visit_dict, save_root, patient_path, read_from_cache=False)
    print('age sex dict loaded')
    medicine_dict = get_medicine(visit_dict, save_root, medicine_path, medicine_mapping_path, read_from_cache=False)
    print('medicine dict loaded')
    operation_dict = get_procedure(visit_dict, save_root, operation_path, operation_mapping_path, read_from_cache=False)
    print('operation dict loaded')
    lab_test_dict = get_lab_test(visit_dict, save_root, lab_test_path, code_name_path, read_from_cache=False)
    print('lab test dict loaded')
    diagnosis_dict = get_diagnosis(visit_dict, save_root, diagnosis_path, diagnosis_mapping_path, read_from_cache=False)
    print('diagnosis dict loaded')
    vital_sign_dict = get_vital_sign(visit_dict, save_root, vital_sign_path, read_from_cache=False)
    print('vital sign dict loaded')
    risk_factor_dict = get_risk_factor(visit_dict, vital_sign_dict, age_sex_dict, operation_dict, cardiac_ope_name_set)

    disease_category_dict = disease_category_fuse(visit_dict, diagnosis_dict)

    save_path = os.path.join(os.path.abspath('../../resource/preprocessed_data/'), 'mimic_unpreprocessed.csv')
    reconstruct(visit_dict, lab_test_dict, operation_dict, age_sex_dict, vital_sign_dict, medicine_dict, diagnosis_dict,
                risk_factor_dict, disease_category_dict, save_path)


def disease_category_fuse(visit_dict, comorbidities_dict):
    '''
    对患者的疾病诊断信息进行分类，将具体疾病映射到更高层次的疾病大类（如心律失常、心肌病等）。
    '''

    # 初始化疾病类别 字典
    disease_category_dict = dict()
    for patient_id in visit_dict:
        disease_category_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            disease_category_dict[patient_id][visit_id] = {
                '心律失常': 0, '心肌病': 0, '冠状动脉粥样硬化性心脏病': 0, '动脉粥样硬化': 0, '心脏瓣膜病': 0
            }

    # 定义疾病类别与候选疾病的映射
    candidate_set = {
        '心律失常': {'窦性心动过速', '窦性心动过缓', '窦性心律不齐', '窦性停搏', '窦房传导阻滞', '病态窦房结综合征', '房性期前收缩',
                 '房性心动过速', '心房扑动', '心房颤动', '预激综合征', '室性期前收缩', '室性心动过速', '房室阻滞'},
        '心肌病': {'扩张型心肌病', '肥厚型心肌病', '限制型心肌病', '心肌炎'},
        '冠状动脉粥样硬化性心脏病': {'心肌梗死', '缺血性心肌病', '心绞痛'},
        '动脉粥样硬化': {'周围动脉病', '心肌梗死', '缺血性心肌病', '心绞痛'},
        '心脏瓣膜病': {'二尖瓣狭窄', '二尖瓣关闭不全', '主动脉瓣狭窄', '主动脉瓣关闭不全', '三尖瓣关闭不全', '肺动脉瓣关闭不全'}
    }

    # 遍历具体疾病诊断数据并归类
    for patient_id in comorbidities_dict:
        for visit_id in comorbidities_dict[patient_id]:
            if not (disease_category_dict.__contains__(patient_id) and
                    disease_category_dict[patient_id].__contains__(visit_id)):
                continue
            disease_dict = comorbidities_dict[patient_id][visit_id]
            for key in candidate_set:
                for item in candidate_set[key]:
                    if int(disease_dict[item]) > 0.5:
                        disease_category_dict[patient_id][visit_id][key] = 1

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    '心律失常': 1,
                    '心肌病': 0,
                    '冠状动脉粥样硬化性心脏病': 1,
                    '动脉粥样硬化': 0,
                    '心脏瓣膜病': 0
                },
                'visit_id2': { ... },
                ...
            },
            'patient_id2': { ... },
            ...
        }
    '''
    return disease_category_dict


def get_risk_factor(visit_dict, vital_sign_dict, age_sex_dict, operation_dict, cardiac_operation_name_set):
    '''
    从患者的生命体征数据、年龄/性别信息、手术信息等中提取风险因子（如年龄超过一定阈值、肥胖、是否做过心脏手术等）。
    该函数根据这些信息生成一个嵌套字典结构，标记每个患者在每次就诊中的风险因子状态。
    '''
    risk_factor_dict = dict()
    for patient_id in visit_dict:
        risk_factor_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            risk_factor_dict[patient_id][visit_id] = {'年龄>40': 0, '年龄>70': 0, '肥胖': 0, '心脏手术': 0}
            if float(age_sex_dict[patient_id][visit_id]['年龄']) > 40:
                risk_factor_dict[patient_id][visit_id]['年龄>40'] = 1
            if float(age_sex_dict[patient_id][visit_id]['年龄']) > 70:
                risk_factor_dict[patient_id][visit_id]['年龄>70'] = 1
            if float(vital_sign_dict[patient_id][visit_id]['BMI']) > 24:
                risk_factor_dict[patient_id][visit_id]['肥胖'] = 1
            for item in cardiac_operation_name_set:
                if float(operation_dict[patient_id][visit_id][item]) > 0.5:
                    risk_factor_dict[patient_id][visit_id]['心脏手术'] = 1

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    '年龄>40': 1,
                    '年龄>70': 0,
                    '肥胖': 1,
                    '心脏手术': 0
                },
                'visit_id2': { ... },
                ...
            },
            ...
        }
    '''
    return risk_factor_dict


def reconstruct(visit_dict, lab_test_dict, operation_dict, age_sex_dict, vital_sign_dict, medicine_dict,
                diagnosis_dict, risk_factor_dict, disease_category_dict, save_path, min_visit=2):
    '''
        整合多个来源的数据（如实验室检查、手术、药物使用、生命体征等），按照患者和就诊 ID 组织这些特征，并将结果保存到一个 CSV 文件中，以便后续使用。
    '''
    included_visit = set()
    for pat_id in visit_dict:
        if len(visit_dict[pat_id]) >= min_visit:
            included_visit.add(pat_id)

    # 构造综合数据字典，将特征值存入嵌套字典
    data_dict = dict()
    for patient_id in visit_dict:
        if patient_id not in included_visit:
            continue

        data_dict[patient_id] = dict()
        visit_list = list()
        for visit_id in visit_dict[patient_id]:
            visit_list.append(int(visit_id))
        visit_list = sorted(visit_list)

        for visit_id in visit_list:
            visit_id = str(visit_id)
            data_dict[patient_id][visit_id] = dict()
            for lab_test in lab_test_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][lab_test] = lab_test_dict[patient_id][visit_id][lab_test][0]
            for operation in operation_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][operation] = operation_dict[patient_id][visit_id][operation]
            for feature in age_sex_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][feature] = age_sex_dict[patient_id][visit_id][feature]
            for vital_sign in vital_sign_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][vital_sign] = vital_sign_dict[patient_id][visit_id][vital_sign]
            for medicine in medicine_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][medicine] = medicine_dict[patient_id][visit_id][medicine]
            for diagnosis in diagnosis_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][diagnosis] = diagnosis_dict[patient_id][visit_id][diagnosis]
            for risk in risk_factor_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][risk] = risk_factor_dict[patient_id][visit_id][risk]
            for category in disease_category_dict[patient_id][visit_id]:
                data_dict[patient_id][visit_id][category] = disease_category_dict[patient_id][visit_id][category]

    # 构造特征列表
    '''
        提取所有特征名称，构造特征列表 feature_list。
        该列表将作为 CSV 文件的表头。
    '''
    feature_list = []
    for patient_id in visit_dict:
        for visit_id in visit_dict[patient_id]:
            for category in disease_category_dict[patient_id][visit_id]:
                feature_list.append(category)
            for risk in risk_factor_dict[patient_id][visit_id]:
                feature_list.append(risk)
            for operation in operation_dict[patient_id][visit_id]:
                feature_list.append(operation)
            for feature in age_sex_dict[patient_id][visit_id]:
                feature_list.append(feature)
            for vital_sign in vital_sign_dict[patient_id][visit_id]:
                feature_list.append(vital_sign)
            for medicine in medicine_dict[patient_id][visit_id]:
                feature_list.append(medicine)
            for diagnosis in diagnosis_dict[patient_id][visit_id]:
                feature_list.append(diagnosis)
            for lab_test in lab_test_dict[patient_id][visit_id]:
                feature_list.append(lab_test)
            break
        break

    # 写入CSV文件
    # 构造表头 head，包含患者 ID、就诊 ID 和所有特征名称。
    data_to_write = []
    head = ['patient_id', 'visit_id']
    for item in feature_list:
        head.append(item)
    data_to_write.append(head)
    for patient_id in data_dict:
        for visit_id in data_dict[patient_id]:
            line = [patient_id, visit_id]
            for index in range(2, len(head)):
                line.append(data_dict[patient_id][visit_id][head[index]])
            data_to_write.append(line)
    with open(save_path, 'w', encoding='utf-8-sig', newline='') as file:
        csv.writer(file).writerows(data_to_write)


def get_procedure(visit_dict, save_root, procedure_path, mapping_file, read_from_cache=True, file_name='procedure.csv'):
    '''
        从手术数据文件中提取患者的手术记录，并将手术代码映射为手术名称。
        它根据患者和就诊 ID 组织成一个嵌套字典结构，用于标记每个患者在每次就诊中是否进行了特定手术。
    '''
    if read_from_cache:
        procedure_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', encoding='utf-8-sig', newline='') as file:
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, feature, value = line
                if not procedure_dict.__contains__(patient_id):
                    procedure_dict[patient_id] = dict()
                if not procedure_dict[patient_id].__contains__(visit_id):
                    procedure_dict[patient_id][visit_id] = dict()
                procedure_dict[patient_id][visit_id][feature] = int(value)
        return procedure_dict
    procedure_dict = dict()
    mapping_dict = dict()
    with open(mapping_file, 'r', encoding='utf-8-sig', newline='') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            name, code, _ = line
            mapping_dict[code] = name
    for patient_id in visit_dict:
        procedure_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            procedure_dict[patient_id][visit_id] = dict()
            for code in mapping_dict:
                procedure_dict[patient_id][visit_id][mapping_dict[code]] = 0

    with open(procedure_path, 'r', encoding='utf-8-sig', newline='') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, visit_id, icd_9 = line[1], line[2], line[4]
            if not (procedure_dict.__contains__(patient_id) and procedure_dict[patient_id].__contains__(visit_id)
                    and mapping_dict.__contains__(icd_9)):
                continue
            procedure_dict[patient_id][visit_id][mapping_dict[icd_9]] = 1

    data_to_write = [['patient_id', 'visit_id', 'operation', 'positive']]
    for patient_id in procedure_dict:
        for visit_id in procedure_dict[patient_id]:
            for feature in procedure_dict[patient_id][visit_id]:
                value = procedure_dict[patient_id][visit_id][feature]
                data_to_write.append([patient_id, visit_id, feature, value])
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        csv.writer(file).writerows(data_to_write)

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    'procedure_name1': 1,
                    'procedure_name2': 0,
                    ...
                },
                ...
            },
            ...
        }
    '''
    return procedure_dict


def get_sex_age(visit_dict, save_root, patient_path, read_from_cache=True, file_name='visit_info.csv'):
    '''
    从患者数据中提取每位患者在每次就诊时的性别和年龄信息。
    '''
    
    # 从缓存文件加载数据
    if read_from_cache:
        sex_age_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', newline='', encoding='utf-8-sig') as file:
            '''
            1. 使用 csv.reader 读取缓存文件。
            2. 跳过表头（islice(csv_reader, 1, None)），逐行读取每个条目。
            3. 按照 patient_id 和 visit_id 构造嵌套字典，并提取以下字段：
                '年龄'：转化为浮点数。
                '性别'：转化为整数（0 或 1）。
            4. 返回提取的字典 sex_age_dict。
            '''
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, sex, age = line
                if not sex_age_dict.__contains__(patient_id):
                    sex_age_dict[patient_id] = dict()
                sex_age_dict[patient_id][visit_id] = {'年龄': float(age), '性别': int(sex)}
        return sex_age_dict

    # 没有缓存，从原始文件提取性别和年龄信息
    # 初始化，遍历 visit_dict，为每个患者和其就诊记录初始化嵌套字典。年龄 和 性别 的初始值分别为 -1（表示未设置）。
    sex_age_dict = dict()
    for patient_id in visit_dict:
        sex_age_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            sex_age_dict[patient_id][visit_id] = {'年龄': -1, '性别': -1}

    with open(patient_path, 'r', newline='', encoding='utf-8-sig') as file:
        '''
        1. 打开患者数据文件，用 csv.reader 逐行读取。
        2. 提取如下字段：
            patient_id：患者 ID。
            sex：性别（可能为 'F' 或 'M'）。
            birthday：出生日期。
        3. 检查数据完整性：
            如果 sex 或 birthday 为空，跳过该条记录。
            将 birthday 转换为 datetime 格式。
        4. 将性别标准化：
            'F' 转为 0。
            'M' 转为 1。
            如果性别值无效，抛出异常。
        5. 遍历患者的每次就诊记录，计算年龄：
            年龄 = (入院时间 - 出生日期).days / 365。
            将性别和年龄信息存入 sex_age_dict。
        '''
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, sex, birthday = line[1: 4]
            if not sex_age_dict.__contains__(patient_id):
                continue
            if len(sex) < 1 or len(birthday) < 10:
                continue
            birthday = datetime.datetime.strptime(birthday, '%Y-%m-%d %H:%M:%S')

            if sex == 'F':
                sex = 0
            elif sex == 'M':
                sex = 1
            else:
                raise ValueError('')
            for visit_id in visit_dict[patient_id]:
                admission_time = visit_dict[patient_id][visit_id]['admit_time']
                age = (admission_time-birthday).days / 365
                sex_age_dict[patient_id][visit_id] = {'年龄': age, '性别': sex}

    # 保存处理结果到缓存文件
    data_to_write = [['patient_id', 'visit_id', '性别', '年龄']]
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        '''
            1. 构造表头 ['patient_id', 'visit_id', '性别', '年龄']。
            2. 遍历 sex_age_dict，将每个患者的每次就诊记录逐行写入。
            3. 使用 csv.writer 将数据保存到缓存文件。
        '''
        for patient_id in sex_age_dict:
            for visit_id in sex_age_dict[patient_id]:
                data_to_write.append([patient_id, visit_id, sex_age_dict[patient_id][visit_id]['性别'],
                                      sex_age_dict[patient_id][visit_id]['年龄']])
        csv.writer(file).writerows(data_to_write)

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    '年龄': 数值,
                    '性别': 数值（0 或 1）
                },
                'visit_id2': { ... },
                ...
            },
            ...
        }
    '''
    return sex_age_dict


def get_vital_sign(visit_dict, save_root, vital_sign_path, read_from_cache=True, file_name='vital_sign.csv'):
    '''
    从原始生命体征数据文件中提取患者的生命体征信息（如血压、身高、体重等），并将其按患者和就诊 ID 组织成嵌套字典结构。
    '''

    # 从缓存文件加载数据
    if read_from_cache:
        vital_sign_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', encoding='utf-8-sig', newline='') as file:
            '''
            1. 使用 csv.reader 读取缓存文件。
            2. 跳过表头（islice(csv_reader, 1, None)），逐行读取每个条目。
            3. 按照 patient_id 和 visit_id 构造嵌套字典，并将特征（如 BMI, 血压High）及其数值存入字典
            '''
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, feature, value = line
                if not vital_sign_dict.__contains__(patient_id):
                    vital_sign_dict[patient_id] = dict()
                if not vital_sign_dict[patient_id].__contains__(visit_id):
                    vital_sign_dict[patient_id][visit_id] = dict()
                vital_sign_dict[patient_id][visit_id][feature] = float(value)
        return vital_sign_dict

    # 没有缓存，从原始文件提取生命体征信息
    # 初始化生命体征字典
    vital_sign_dict = dict()
    for patient_id in visit_dict:
        vital_sign_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            vital_sign_dict[patient_id][visit_id] = {
                '血压Low': [-1, datetime.datetime(2500, 1, 1, 0, 0, 0, 0)],
                '血压high': [-1, datetime.datetime(2500, 1, 1, 0, 0, 0, 0)],
                'height': [-1, datetime.datetime(2500, 1, 1, 0, 0, 0, 0)],
                'weight': [-1, datetime.datetime(2500, 1, 1, 0, 0, 0, 0)],
            }

    with open(vital_sign_path, 'r', newline='', buffering=-1, encoding='utf-8-sig') as file:
        '''
            1. 打开原始生命体征数据文件，用 csv.reader 逐行读取。
            2. 提取如下字段：
                patient_id：患者 ID。
                visit_id：就诊 ID。
                item_id：体征项目的 ID。
                chart_time：数据记录时间。
                value：体征值。
                unit：单位（如 cm、kg）。
            3. 检查数据有效性：如果没有记录时间或数值为空，跳过该条记录。
            4. 将 value 转为浮点数，将 chart_time 转为 datetime 格式。
        '''
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, visit_id, item_id, chart_time, value, unit = \
                line[1], line[2], line[4], line[5], line[9], line[10]
            if not (vital_sign_dict.__contains__(patient_id) and vital_sign_dict[patient_id].__contains__(visit_id)):
                continue
            if len(chart_time) < 10 or len(value) < 1:
                continue
            value = float(value)
            unit = unit.lower()
            chart_time = datetime.datetime.strptime(chart_time, '%Y-%m-%d %H:%M:%S')
            # 1 lbs = 0.453592 kg
            # 1 inches = 2.54 cm
            # 1 feet = 30.48 cm
            # 1 oz = 0.0283495 kg
            # SBP
            if item_id == '51' or item_id == '455' or item_id == '220179' or item_id == '220050':
                if unit != 'mmhg':
                    continue
                if vital_sign_dict[patient_id][visit_id]['血压high'][1] > chart_time:
                    vital_sign_dict[patient_id][visit_id]['血压high'] = value, chart_time
            # dbp
            if item_id == '8368' or item_id == '8441' or item_id == '220180' or item_id == '220051':
                if unit != 'mmhg':
                    continue
                if vital_sign_dict[patient_id][visit_id]['血压Low'][1] > chart_time:
                    vital_sign_dict[patient_id][visit_id]['血压Low'] = value, chart_time
            # height
            if item_id == '216' or item_id == '1394' or item_id == '226707' or item_id == '226730' or item_id == '920':
                if unit == 'cm':
                    value = value
                elif unit == 'inch' or unit == 'inches':
                    value = value * 2.54
                elif unit == 'feet' or unit == 'feets':
                    value = value * 30.48
                else:
                    continue
                if vital_sign_dict[patient_id][visit_id]['height'][1] > chart_time and 250 > value > 50:
                    vital_sign_dict[patient_id][visit_id]['height'] = value, chart_time
            # weight
            if item_id == '3580' or item_id == '3581' or item_id == '3582' or item_id == '224639' or item_id == '763' \
                    or item_id == '226512' or item_id == '226531' or item_id == '762':
                if unit == 'kg':
                    value = value
                elif unit == 'lbs' or item_id == '226531':
                    value = value * 0.453592
                elif unit == 'oz':
                    value = value * 0.0283495
                else:
                    continue
                if vital_sign_dict[patient_id][visit_id]['weight'][1] > chart_time and 300 > value > 20:
                    vital_sign_dict[patient_id][visit_id]['weight'] = value, chart_time

    # 计算BMI
    for patient_id in vital_sign_dict:
        for visit_id in vital_sign_dict[patient_id]:
            weight = vital_sign_dict[patient_id][visit_id]['weight'][0]
            height = vital_sign_dict[patient_id][visit_id]['height'][0]
            if weight == -1 or height == -1:
                bmi = -1
            else:
                bmi = weight * 10000 / height / height
            vital_sign_dict[patient_id][visit_id]['BMI'] = bmi, -1
            for feature in vital_sign_dict[patient_id][visit_id]:
                vital_sign_dict[patient_id][visit_id][feature] = \
                    float(vital_sign_dict[patient_id][visit_id][feature][0])

    data_to_write = [['patient_id', 'visit_id', 'feature', 'value']]
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        for patient_id in vital_sign_dict:
            for visit_id in vital_sign_dict[patient_id]:
                for feature in vital_sign_dict[patient_id][visit_id]:
                    value = vital_sign_dict[patient_id][visit_id][feature]
                    data_to_write.append([patient_id, visit_id, feature, value])
        csv.writer(file).writerows(data_to_write)
    
    '''
        {
            'patient_id1': {
                'visit_id1': {
                    '血压Low': 数值,
                    '血压high': 数值,
                    'height': 数值,
                    'weight': 数值,
                    'BMI': 数值
                },
                ...
            },
            ...
        }
    '''
    return vital_sign_dict


def get_medicine(visit_dict, save_root, medicine_path, mapping_file, read_from_cache=True, file_name='medicine.csv',
                 off_set=48):
     '''
        从原始药物数据文件中提取患者的用药信息，并将其映射到特定的药物类别。
        它按照患者和就诊 ID 组织成嵌套字典结构，用于标记每个患者在每次就诊中使用的药物类别。
     '''
    if read_from_cache:
        medicine_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', encoding='utf-8-sig', newline='') as file:
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, drug, usage = line
                if not medicine_dict.__contains__(patient_id):
                    medicine_dict[patient_id] = dict()
                if not medicine_dict[patient_id].__contains__(visit_id):
                    medicine_dict[patient_id][visit_id] = dict()
                medicine_dict[patient_id][visit_id][drug] = int(usage)
        return medicine_dict

    medicine_dict = dict()
    name_cate_dict = dict()
    with open(mapping_file, 'r', encoding='utf-8-sig', newline='') as file:
        csv_reader = csv.reader(file)
        for line in csv_reader:
            category, _, english_name = line
            if name_cate_dict.__contains__(english_name.lower()):
                name_cate_dict[english_name.lower()].append(category)
            else:
                name_cate_dict[english_name.lower()] = [category]
    for patient_id in visit_dict:
        medicine_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            medicine_dict[patient_id][visit_id] = dict()
            for key in name_cate_dict:
                for item in name_cate_dict[key]:
                    medicine_dict[patient_id][visit_id][item] = 0

    with open(medicine_path, 'r', encoding='utf-8-sig', newline='') as file:
        '''
        1. 打开原始药物数据文件，用 csv.reader 逐行读取。
        2. 提取如下字段：
                patient_id：患者 ID。
                visit_id：就诊 ID。
                start_date：药物使用开始时间。
        3. 检查数据有效性：
                如果 start_date 为空，跳过该条记录。
                检查当前患者和就诊记录是否存在于 visit_dict 中。
        4. 判断药物使用时间是否在出院时间前的 off_set 小时内：
                如果不满足条件，跳过该条记录。
        5. 拼接药物名称（line[7] + "_" + line[8] + '_' + line[9]），将其转为小写。
        6. 遍历 name_cate_dict，检查药物名称是否包含特定关键字。
                如果匹配成功，将对应药物类别标记为 1。
        '''
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, visit_id, start_date = line[1], line[2], line[5]
            if len(start_date) < 10:
                continue
            if not (visit_dict.__contains__(patient_id) and visit_dict[patient_id].__contains__(visit_id)):
                continue
            end_time = datetime.datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
            time_difference = (visit_dict[patient_id][visit_id]['discharge_time'] - end_time)
            if (time_difference.seconds+time_difference.days*24*3600)/3600 > off_set:
                continue

            drug_name = (line[7]+"_"+line[8]+'_'+line[9]).lower()
            for key in name_cate_dict:
                if drug_name.__contains__(key):
                    for item in name_cate_dict[key]:
                        medicine_dict[patient_id][visit_id][item] = 1

    data_to_write = [['patient_id', 'visit_id', 'medicine', 'usage']]
    for patient_id in medicine_dict:
        for visit_id in medicine_dict[patient_id]:
            for drug in medicine_dict[patient_id][visit_id]:
                data_to_write.append([patient_id, visit_id, drug, medicine_dict[patient_id][visit_id][drug]])
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        csv.writer(file).writerows(data_to_write)

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    'med_category1': 1,
                    'med_category2': 0,
                    ...
                },
                ...
            },
            ...
        }
    '''
    return medicine_dict


def get_lab_test(visit_dict, save_root, lab_test_path, code_name_path, read_from_cache=True, file_name='lab_test.csv',
                 min_count=10000):
     '''
     从实验室检查数据文件中提取患者的实验室检查结果，并将其按患者和就诊 ID 组织成嵌套字典结构。
     '''
    if read_from_cache:
        lab_test_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', encoding='utf-8-sig', newline='') as file:
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, feature, value, record_time = line
                record_time = datetime.datetime.strptime(record_time, '%Y-%m-%d %H:%M:%S')
                result_list = re.findall('[-+]?[\d]+(?:,\d\d\d)*[.]?\d*(?:[eE][-+]?\d+)?', value)
                if len(result_list) > 0:
                    value = float(result_list[0])
                if not lab_test_dict.__contains__(patient_id):
                    lab_test_dict[patient_id] = dict()
                if not lab_test_dict[patient_id].__contains__(visit_id):
                    lab_test_dict[patient_id][visit_id] = dict()
                lab_test_dict[patient_id][visit_id][feature] = [value, record_time]
        return lab_test_dict

    # 构建code item mapping
    code_name_map = dict()
    with open(code_name_path, 'r', newline='', encoding='utf-8-sig') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            lab_code, name, label = line[1: 4]
            code_name_map[lab_code] = name + '_' + label

    # lab test放弃mapping file，扫描一遍文件，选择此处发生较多的lab test
    mapping_dict = dict()
    with open(lab_test_path, 'r', newline='', encoding='utf-8-sig') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            lab_code = line[3]
            if mapping_dict.__contains__(lab_code):
                mapping_dict[lab_code] += 1
            else:
                mapping_dict[lab_code] = 1
    mapping_set = set()
    for key in mapping_dict:
        if mapping_dict[key] > min_count:
            mapping_set.add(key)

    lab_test_dict = dict()
    for patient_id in visit_dict:
        lab_test_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            lab_test_dict[patient_id][visit_id] = dict()
            for code in mapping_set:
                lab_test_dict[patient_id][visit_id][code] = \
                    [-1, datetime.datetime(2500, 1, 1, 0, 0, 0, 0)]

    with open(lab_test_path, 'r', newline='', encoding='utf-8-sig') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, visit_id, lab_code, test_time, result = line[1: 6]
            if not (lab_test_dict.__contains__(patient_id) and lab_test_dict[patient_id].__contains__(visit_id)):
                continue
            if (not mapping_set.__contains__(lab_code)) or len(test_time) < 10:
                continue
            test_time = datetime.datetime.strptime(test_time, '%Y-%m-%d %H:%M:%S')

            if test_time < lab_test_dict[patient_id][visit_id][lab_code][1]:
                result_list = re.findall('[-+]?[\d]+(?:,\d\d\d)*[.]?\d*(?:[eE][-+]?\d+)?', result)
                if len(result_list) > 0:
                    if result_list[0].__contains__(','):
                        result_list[0] = result_list[0].replace(',', '')
                    result = float(result_list[0])
                lab_test_dict[patient_id][visit_id][lab_code] = [result, test_time]

    data_to_write = [['patient_id', 'visit_id', 'feature', 'value', 'record_time']]
    for patient_id in lab_test_dict:
        for visit_id in lab_test_dict[patient_id]:
            for feature in lab_test_dict[patient_id][visit_id]:
                feature_name = code_name_map[feature]
                value, record_time = lab_test_dict[patient_id][visit_id][feature]
                data_to_write.append([patient_id, visit_id, feature_name, value, record_time])
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        csv.writer(file).writerows(data_to_write)

    lab_new_dict = dict()
    for patient_id in lab_test_dict:
        lab_new_dict[patient_id] = dict()
        for visit_id in lab_test_dict[patient_id]:
            lab_new_dict[patient_id][visit_id] = dict()
            for feature in lab_test_dict[patient_id][visit_id]:
                feature_name = code_name_map[feature]
                value, record_time = lab_test_dict[patient_id][visit_id][feature]
                lab_new_dict[patient_id][visit_id][feature_name] = value, record_time

    '''
        {
            'patient_id1': {
                'visit_id1': {
                    'lab_test_name1': [value, record_time],
                    'lab_test_name2': [value, record_time],
                    ...
                },
                ...
            },
            ...
        }
    '''
    return lab_new_dict


def get_admissions(admission_path, save_root, read_from_cache=True, file_name='admission.csv'):
    '''
    提取患者的入院数据
    '''
    
    # 如果有缓存，从缓存文件中加载数据
    if read_from_cache:
        visit_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', newline='', encoding='utf-8-sig') as file:
            '''
            1. 用 csv.reader 打开缓存文件
            2. 跳过表头(islice(csv_reader, 1, None))，逐行读取数据
            3. 将入院时间（admit_time）、出院时间（discharge_time）和死亡时间（death_time）解析为 datetime 对象
            4. 按 patient_id 和 visit_id 组织成嵌套字典结构
            '''
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, admit_time, discharge_time, death_time, ethnicity = line
                admit_time = datetime.datetime.strptime(admit_time, '%Y-%m-%d %H:%M:%S')
                discharge_time = datetime.datetime.strptime(discharge_time, '%Y-%m-%d %H:%M:%S')
                death_time = datetime.datetime.strptime(death_time, '%Y-%m-%d %H:%M:%S')
                if not visit_dict.__contains__(patient_id):
                    visit_dict[patient_id] = dict()
                visit_dict[patient_id][visit_id] = {'admit_time': admit_time, 'discharge_time': discharge_time,
                                                    'death_time': death_time, 'ethnicity': ethnicity}
        return visit_dict
    
    # 如果没有缓存，从原始文件中提取数据
    visit_dict = dict()
    with open(admission_path, 'r', newline='', encoding='utf-8-sig') as file:
        '''
        1. 用 csv.reader 打开原始入院数据文件
        2. 跳过表头，从第二行开始逐行读取
        3. 提取几个字段：patient_id, visit_id, admit_time, discharge_time, death_time, ethnicity
        4. 按 patient_id 和 visit_id 组织成字典
        '''
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            patient_id, visit_id, admit_time, discharge_time, death_time = line[1: 6]
            ethnicity = line[13]

            admit_time = datetime.datetime.strptime(admit_time, '%Y-%m-%d %H:%M:%S')
            discharge_time = datetime.datetime.strptime(discharge_time, '%Y-%m-%d %H:%M:%S')
            if len(death_time) > 0:
                death_time = datetime.datetime.strptime(death_time, '%Y-%m-%d %H:%M:%S')
            else:
                death_time = datetime.datetime.strptime('1900-01-01 00:00:00', '%Y-%m-%d %H:%M:%S')
            if not visit_dict.__contains__(patient_id):
                visit_dict[patient_id] = dict()
            visit_dict[patient_id][visit_id] = {'admit_time': admit_time, 'discharge_time': discharge_time,
                                                "death_time": death_time, "ethnicity": ethnicity}

    # 从原始数据处理后，保存到缓存文件，方便后续使用
    with open(os.path.join(save_root, file_name), 'w', newline='', encoding='utf-8-sig') as file:
        '''
        1. 构造表头行 ['patient_id', 'visit_id', 'admit_time', 'discharge_time', 'death_time', 'ethnicity']
        2. 遍历 visit_dict，将每个患者的就诊信息逐行写入
        3. 用 csv.writer 将数据写入缓存文件
        '''
        data_to_write = [['patient_id', 'visit_id', 'admit_time', 'discharge_time', 'death_time', 'ethnicity']]
        for patient_id in visit_dict:
            for visit_id in visit_dict[patient_id]:
                admit_time = visit_dict[patient_id][visit_id]['admit_time']
                discharge_time = visit_dict[patient_id][visit_id]['discharge_time']
                death_time = visit_dict[patient_id][visit_id]['death_time']
                ethnicity = visit_dict[patient_id][visit_id]['ethnicity']
                data_to_write.append([patient_id, visit_id, admit_time, discharge_time, death_time, ethnicity])
        csv.writer(file).writerows(data_to_write)

    '''
    返回的嵌套字典
    visit_dict = {
        'patient_id1': {
            'visit_id1': {
                'admit_time': datetime.datetime(...),
                'discharge_time': datetime.datetime(...),
                'death_time': datetime.datetime(...),
                'ethnicity': 'ethnicity_value'
            },
            ...
        },
    ...
    }
    '''
    return visit_dict


def get_diagnosis(visit_dict, save_root, diagnosis_path, mapping_file, read_from_cache=True, file_name='diagnosis.csv'):
    '''
    从诊断数据文件中提取患者的诊断信息，并将诊断结果映射到特定的疾病名称
    '''

    # 如果有缓存，从缓存文件中读取数据
    if read_from_cache:
        diagnosis_dict = dict()
        with open(os.path.join(save_root, file_name), 'r', encoding='utf-8-sig', newline='') as file:
            '''
            1. 使用 csv.reader 读取缓存文件
            2. 跳过表头（islice(csv_reader, 1, None)），逐行读取每个条目
            3. 按照 patient_id 和 visit_id 构造嵌套字典，存储诊断结果，disease 表示疾病名称，positive 表示是否诊断为该疾病（通常为 0 或 1）
            '''
            csv_reader = csv.reader(file)
            for line in islice(csv_reader, 1, None):
                patient_id, visit_id, disease, positive = line
                if not diagnosis_dict.__contains__(patient_id):
                    diagnosis_dict[patient_id] = dict()
                if not diagnosis_dict[patient_id].__contains__(visit_id):
                    diagnosis_dict[patient_id][visit_id] = dict()
                diagnosis_dict[patient_id][visit_id][disease] = int(positive)
        return diagnosis_dict

    # 如果未启用缓存（read_from_cache=False），函数会从原始文件中提取数据
    diagnosis_dict = dict()
    diagnosis_map_list = list()
    diagnosis_set = set()
    with open(mapping_file, 'r', encoding='utf-8-sig', newline='') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            diagnosis_map_list.append([line[1], line[4]])
            diagnosis_set.add(line[1])

    # 构建基本映射
    for patient_id in visit_dict:
        diagnosis_dict[patient_id] = dict()
        for visit_id in visit_dict[patient_id]:
            diagnosis_dict[patient_id][visit_id] = dict()
            for item in diagnosis_set:
                diagnosis_dict[patient_id][visit_id][item] = 0

    with open(diagnosis_path, 'r', newline='', encoding='utf-8-sig') as file:
        csv_reader = csv.reader(file)
        for line in islice(csv_reader, 1, None):
            _, patient_id, visit_id, _, icd_code = line
            if not (diagnosis_dict.__contains__(patient_id) and diagnosis_dict[patient_id].__contains__(visit_id)):
                continue
            for item in diagnosis_map_list:
                name, code = item
                if icd_code.__contains__(code):
                    diagnosis_dict[patient_id][visit_id][name] = 1

    data_to_write = [['patient_id', 'visit_id', 'disease', 'positive']]
    for patient_id in diagnosis_dict:
        for visit_id in diagnosis_dict[patient_id]:
            for disease in diagnosis_dict[patient_id][visit_id]:
                data_to_write.append([patient_id, visit_id, disease, diagnosis_dict[patient_id][visit_id][disease]])
    with open(os.path.join(save_root, file_name), 'w', encoding='utf-8-sig', newline='') as file:
        csv.writer(file).writerows(data_to_write)


    '''
        {
            'patient_id1': {
                'visit_id1': {
                    'disease1': 1,
                    'disease2': 0,
                    ...
                },
                ...
            },
            ...
        }
    '''
    return diagnosis_dict


if __name__ == '__main__':
    main()
