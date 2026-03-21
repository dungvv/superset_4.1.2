# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import io
from typing import Any

import pandas as pd


import os
from PIL import Image
from datetime import datetime

from superset.utils.core import GenericDataType



def format_font(workbook):
	# Định nghĩa các format
	formats = {
		'en_header_format': workbook.add_format({"bold": True,"font_size": 16,"align": "center",}),
		'vie_header_format': workbook.add_format({"bold": True,"italic": True,"font_size": 14,"align": "center",}),
		'title_format': workbook.add_format({"bold": True,"italic": True,"underline": True,"font_size": 11,"align": "left",}),
		'bolded_format': workbook.add_format({'bold': True,"font_size": 11,"align": "left"}),
		',d': workbook.add_format({'num_format': '#,##0'}),
		'.1s': None,  # Xử lý trong Python
		'.3s': None,  # Xử lý trong Python
		',.%': workbook.add_format({'num_format': '#,##0.0%'}),
		',.2%': workbook.add_format({'num_format': '#,##0.00%'}),
		',.3%': workbook.add_format({'num_format': '#,##0.000%'}),
		'.4r': workbook.add_format({'num_format': '0'}),
		',.1f': workbook.add_format({'num_format': '#,##0.0'}),
		',.2f': workbook.add_format({'num_format': '#,##0.00'}),
		'int_format': workbook.add_format({'num_format': '#,##0'}),
		'float_format': workbook.add_format({'num_format': '#,##0.00'}),
		'%d/%m/%Y': workbook.add_format({'num_format': 'dd/mm/yyyy'}),
		'%m/%d/%Y': workbook.add_format({'num_format': 'mm/dd/yyyy'}),
		'%Y-%m-%d': workbook.add_format({'num_format': 'yyyy-mm-dd'}),
		'%d/%m/%Y %H:%M:%S' : workbook.add_format({'num_format': 'dd/mm/yyyy hh:mm:ss'}),
		'%d-%m-%Y %H:%M:%S': workbook.add_format({'num_format': 'dd-mm-yyyy hh:mm:ss'}),
		'%Y/%m/%d %H:%M:%S': workbook.add_format({'num_format': 'yyyy/mm/dd hh:mm:ss'}),
		'%Y-%m-%d %H:%M:%S': workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'}),
		'%H:%M:%S': workbook.add_format({'num_format': 'hh:mm:ss'}),
		'date_format': workbook.add_format({'num_format': 'yyyy-mm-dd'}),
		'datetime_format' : workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'}),
		'SMART_NUMBER': workbook.add_format({'num_format': '#,##0'}),
	}

	return formats


def col_to_excel(col_num):
    """Chuyển số cột (0-indexed) thành ký tự Excel (1-indexed)."""
    col_str = ""
    while col_num >= 0:
        col_str = chr(col_num % 26 + 65) + col_str
        col_num = col_num // 26 - 1
    return col_str


def format_table(worksheet, df, startrow):
	(max_row, max_col) = df.shape

	print(f'Max Row = {max_row}; Max Col = {max_col}')

	start_col_letter = "A"  # Cột bắt đầu luôn là A
	end_col_letter = col_to_excel(max_col - 1)  # Cột kết thúc
	table_range = f"{start_col_letter}{startrow + 1}:{end_col_letter}{(startrow + 1) + max_row}"

	print(f'Table Range: {table_range}')

	worksheet.add_table(table_range, {
		"columns": [{"header": col_name} for col_name in df.columns],
		"style": "Table Style Medium 7"
	})

def format_column(worksheet, df, column_format, formats):
    for col_idx, col_name in enumerate(df.columns):
        max_len = min(
            max(
                df[col_name].astype(str).map(len).max(),
                len(col_name)
            ) + 5,
            50
        )

        if col_name in column_format:
            format_col = column_format.get(col_name)
            if format_col in formats:
                worksheet.set_column(col_idx, col_idx, max_len, formats[format_col])
            else:
                worksheet.set_column(col_idx, col_idx, max_len)
        elif pd.api.types.is_float_dtype(df[col_name]):
            worksheet.set_column(col_idx, col_idx, max_len, formats['float_format'])
        elif pd.api.types.is_integer_dtype(df[col_name]):
            worksheet.set_column(col_idx, col_idx, max_len, formats['int_format'])
        elif pd.api.types.is_datetime64_any_dtype(df[col_name]):
            if df[col_name].dt.time.eq(datetime.min.time()).all():
                worksheet.set_column(col_idx, col_idx, max_len, formats['%d/%m/%Y'])
            else:
                worksheet.set_column(col_idx, col_idx, max_len, formats['%d/%m/%Y %H:%M:%S'])
        else:
            worksheet.set_column(col_idx, col_idx, max_len)


def add_logo(worksheet, logo_path):
	if logo_path and os.path.exists(logo_path):
		with Image.open(logo_path) as img:
			original_width, original_height = img.size

		desired_width = 1.16 * 96
		desired_height = 0.7 * 96
		x_scale = desired_width / original_width
		y_scale = desired_height / original_height

		worksheet.insert_image("A1", logo_path, {
			"x_scale": x_scale,
			"y_scale": y_scale,
			"x_offset": 10,
			"y_offset": 10,
		})

def replace_column_config(column_config):
	# Process to replace subkey value with parent key value
	for key, sub_dict in column_config.items():
		if isinstance(sub_dict, dict):  # Check if value is a dictionary
			for sub_key, value in sub_dict.items():
				# Replace parent key's value with subkey's value
				column_config[key] = value
				break  # Exit after first key-value pair
	
	return column_config

def extract_number_config(column_config):
    """
    Hàm lọc các cột trong column_config có chứa key 'd3NumberFormat'.

    Args:
        column_config (dict): Dictionary chứa cấu hình các cột.

    Returns:
        dict: Dictionary chứa các cột có key 'd3NumberFormat'.
    """
    number_config = {
        key: value for key, value in column_config.items()
        if any(k.strip() == 'd3NumberFormat' for k in value)
    }
    return number_config

def df_to_excel(df: pd.DataFrame, filename: str | None = None, desciption: str | None = None, extra_form_data: dict | None = None, column_config: dict | None = None, **kwargs: Any) -> Any:
    print('####################')
    print('File superset/utils/excel.py')
    print('####################')

    output = io.BytesIO()

    logo_path = '/app/superset/static/assets/images/logo-com.png'

    print(f'column_config: {column_config}')

    column_format = []

    print(f"Kiểu dữ liệu của df trước khi biến đổi:")
    print(df.dtypes)

    if column_config is not None:
        # Tạo biến number_config chứa các key có subkey là 'd3NumberFormat'
        number_config = [key for key, value in column_config.items() if isinstance(value, dict) and 'd3NumberFormat' in value]
        print(f'number_config: {number_config}')

        # Chuyển đổi subvalue của subkey thành value của parent key
        column_format = replace_column_config(column_config)

        print(f"Các thuộc tính của column_format:")
        print(column_format)
        print('\n')

        ## Chuyển đổi kiểu dữ liệu trong Data Frame
        # Convert tất cả các trường Finance sang dạng Float
        for col_name in df.columns:
            if col_name in number_config:
                print(f'Number Column:', col_name)
                df[col_name] = pd.to_numeric(df[col_name], errors='coerce')

    # Kiểu timezones hiện tại không được hỗ trợ tại Superset 3.1.3
    for column in df.select_dtypes(include=["datetimetz"]).columns:
        df[column] = df[column].astype(str)

    # Nếu tất cả giá trị thời gian là 00:00:00, chuyển về kiểu ngày (date)
    for column in df.select_dtypes(include=['datetime64']).columns:
        if df[column].dt.time.eq(datetime.min.time()).all():
            df[column] = df[column].dt.date

    print(f"Kiểu dữ liệu của df sau khi biến đổi:")
    print(df.dtypes)
    print('\n')
    
    # Count số lượng Filter
    if extra_form_data.get('filters') is None and extra_form_data.get('time_range') is None:
        col_filter = 0
    elif extra_form_data.get('filters') is None and extra_form_data.get('time_range') is not None:
        col_filter = 1
    elif extra_form_data.get('filters') is not None and extra_form_data.get('time_range') is None:
        col_filter = len(extra_form_data.get('filters'))
    elif extra_form_data.get('filters') is not None and extra_form_data.get('time_range') is not None:
        col_filter = len(extra_form_data.get('filters')) + 1
    else:
        col_filter = 0
        print("Bug nè - Ở file superset/utils/excel.py - Fix thôi :v")

    print(f"Số lượng Filter: {col_filter}")
    print('\n')
    
    row_index = 3
    column_index = int(len(df.columns) / 2)
    # startrow = dòng bắt đầu đặt tên báo cáo + 3 dòng (tên báo cáo English, Vie và ngày xuất báo cáo) + số lượng dòng cho filer + 2 dòng để bắt đầu hiển thị dữ liệu
    startrow = row_index + 3 + col_filter + 2
    
    # pylint: disable=abstract-class-instantiated
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # index=False: Bỏ Index khi Export
        # startrow: Lùi xuống n dòng
        df.to_excel(writer, index=False, startrow=startrow, **kwargs)

        # Lấy đối tượng workbook và worksheet
        workbook = writer.book
        worksheet = writer.sheets[kwargs.get("sheet_name", "Sheet1")]

        formats = format_font(workbook)

        en_report_name= filename.upper()

        # Hiển thị kết quả dịch
        print('####################')
        print("Original: ", en_report_name)
        print("Desciption: ", desciption)
        print('####################')
        
        # Format Table
        format_table(worksheet, df, startrow)

        # Format Column và Autofit Column Width
        format_column(worksheet, df, column_format, formats)

        # Thêm logo vào file Excel
        add_logo(worksheet, logo_path)    

        # Tên báo cáo và ngày xuất báo cáo
        worksheet.write(row_index, column_index, en_report_name, formats['en_header_format'])
        print(row_index)
        row_index += 1
        worksheet.write(row_index, column_index, desciption, formats['vie_header_format'])
        print(row_index)
        row_index += 1
        worksheet.write(row_index, column_index + 1, f"Export Date: {datetime.now().strftime('%d/%m/%Y')}", formats['title_format'])    
        print(row_index)
        row_index += 1
        worksheet.write(row_index, 1, 'Filters:', formats['title_format'])
        row_index += 1

        if extra_form_data.get('time_range') is not None:
            worksheet.write(row_index, 1, 'Time Range', formats['bolded_format'])
            worksheet.write(row_index, 2, extra_form_data.get('time_range'))
            row_index += 1
        
        if extra_form_data.get('filters') is not None:
            for filter_item in extra_form_data.get("filters"):
                val_value = ", ".join(map(str, filter_item.get('val')))
                worksheet.write(row_index, 1, filter_item.get('col'), formats['bolded_format'])
                worksheet.write(row_index, 2, val_value)
                row_index += 1

        # Ghi dữ liệu vào từng ô với định dạng ngày cụ thể
        for col_num, col_name in enumerate(df.columns):
            for row_num, value in enumerate(df[col_name], start=startrow+1):
                if col_name in column_format:
                    format_key = column_format[col_name]
                    if pd.isna(value) or value in [float('inf'), float('-inf')]:
                        value=""
						
                    if format_key == '%d/%m/%Y':
                        worksheet.write(row_num, col_num, value, formats['%d/%m/%Y'])
                    if format_key == '%m/%d/%Y':
                        worksheet.write(row_num, col_num, value, formats['%m/%d/%Y'])
                    if format_key == '%Y-%m-%d':
                        worksheet.write(row_num, col_num, value, formats['%Y-%m-%d'])
                    if format_key == '%d/%m/%Y %H:%M:%S':
                        worksheet.write(row_num, col_num, value, formats['%d/%m/%Y %H:%M:%S'])
                    if format_key == '%d-%m-%Y %H:%M:%S':
                        worksheet.write(row_num, col_num, value, formats['%d-%m-%Y %H:%M:%S'])
                    if format_key == '%Y/%m/%d %H:%M:%S':
                        worksheet.write(row_num, col_num, value, formats['%Y/%m/%d %H:%M:%S'])
                    if format_key == '%Y-%m-%d %H:%M:%S':
                        worksheet.write(row_num, col_num, value, formats['%Y-%m-%d %H:%M:%S'])    
                    if format_key == '%H:%M:%S':
                        worksheet.write(row_num, col_num, value, formats['%H:%M:%S'])
                    if format_key == 'date_format':
                        worksheet.write(row_num, col_num, value, formats['date_format'])
                    if format_key == 'datetime_format':
                        worksheet.write(row_num, col_num, value, formats['datetime_format'])
                else:
                    if pd.isna(value) or value in [float('inf'), float('-inf')]:
                        value=""
                    worksheet.write(row_num, col_num, value)

    return output.getvalue()


# def df_to_excel(df: pd.DataFrame, **kwargs: Any) -> Any:
#     output = io.BytesIO()

#     # pylint: disable=abstract-class-instantiated
#     with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
#         df.to_excel(writer, **kwargs)

#     return output.getvalue()


def apply_column_types(
    df: pd.DataFrame, column_types: list[GenericDataType]
) -> pd.DataFrame:
    for column, column_type in zip(df.columns, column_types):
        if column_type == GenericDataType.NUMERIC:
            try:
                df[column] = pd.to_numeric(df[column])
            except ValueError:
                df[column] = df[column].astype(str)
        elif pd.api.types.is_datetime64tz_dtype(df[column]):
            # timezones are not supported
            df[column] = df[column].astype(str)
    return df
