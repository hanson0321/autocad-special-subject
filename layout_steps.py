//這裡解決了問題二，指定靠牆+處理象限的問題(目前指定ATM)
import gurobipy as gp
from gurobipy import GRB
import time
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib
from tools import KPtest
from tools import coordinate_flipping as flip
from tools import get_feasible_area
from dxf_tools import dxf_manipulation
import re
import ezdxf

DualReductions = 0

def get_dxf_bounds(doc_path):
    # 讀取 DXF 文件
    doc = ezdxf.readfile(doc_path)

    # 初始化邊界變量
    min_x, min_y = float('inf'), float('inf')
    max_x, max_y = float('-inf'), float('-inf')

    # 遍歷所有的實體
    for entity in doc.entities:
        if hasattr(entity.dxf, 'start') and hasattr(entity.dxf, 'end'):
            x1, y1 = entity.dxf.start[0], entity.dxf.start[1]
            x2, y2 = entity.dxf.end[0], entity.dxf.end[1]
            min_x, min_y = min(min_x, x1, x2), min(min_y, y1, y2)
            max_x, max_y = max(max_x, x1, x2), max(max_y, y1, y2)
        elif hasattr(entity, 'get_points'):
            points = entity.get_points()
            for x, y in points:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)

    return min_x, min_y, max_x, max_y


def calculate_midpoint(min_x, min_y, max_x, max_y):
    mid_x = (min_x + max_x) / 2
    mid_y = (min_y + max_y) / 2
    return mid_x, mid_y


def get_door(doc_path):
    door_segments = []

    # 讀取 DXF 文件
    doc = ezdxf.readfile(doc_path)

    # 遍歷所有的實體
    for entity in doc.entities:
        # 處理LINE實體
        if entity.dxftype() == 'LINE' and entity.dxf.layer == 'door':
            x1 = round(entity.dxf.start[0], 2)
            y1 = round(entity.dxf.start[1], 2)
            x2 = round(entity.dxf.end[0], 2)
            y2 = round(entity.dxf.end[1], 2)
            door_segments.append([x1, y1, x2, y2])

        # 處理LWPOLYLINE和POLYLINE實體
        elif entity.dxftype() in ['LWPOLYLINE', 'POLYLINE'] and entity.dxf.layer == 'door':
            points = entity.get_points()
            for i in range(len(points) - 1):
                x1, y1 = round(points[i][0], 2), round(points[i][1], 2)
                x2, y2 = round(points[i + 1][0], 2), round(points[i + 1][1], 2)
                door_segments.append([x1, y1, x2, y2])

            # 若多段線是封閉的，則連接最後一個點與第一個點
            if entity.is_closed:
                x1, y1 = round(points[-1][0], 2), round(points[-1][1], 2)
                x2, y2 = round(points[0][0], 2), round(points[0][1], 2)
                door_segments.append([x1, y1, x2, y2])

    return door_segments


def determine_quadrant(x, y, x_mid, y_mid):
    if x > x_mid and y > y_mid:
        return 1
    elif x < x_mid and y > y_mid:
        return 2
    elif x < x_mid and y < y_mid:
        return 3
    elif x > x_mid and y < y_mid:
        return 4

def get_opposite_quadrant(door_quadrant):
    return {1: 3, 2: 4, 3: 1, 4: 2}[door_quadrant]

def layout_opt_group1(obj_params, COUNTER_SPACING, SPACE_WIDTH, SPACE_HEIGHT, OPENDOOR_SPACING, LINEUP_SPACING,
                      unusable_gridcell, doc_path, center_x, center_y):

    # 獲取門的象限並確定ATM應該所在的象限
    door_segments = get_door(doc_path)
    door_x, door_y = door_segments[0][0], door_segments[0][1]  # 取第一個門段的起始點
    door_quadrant = determine_quadrant(door_x, door_y, center_x, center_y)  # 修改這裡
    atm_quadrant = get_opposite_quadrant(door_quadrant)

    print(f"空間的中點: ({center_x}, {center_y})")
    print(f"門的位置: ({door_x}, {door_y}) 屬於象限: {door_quadrant}")
    print(f"ATM 應該在的象限: {atm_quadrant}")

    # Create a Gurobi model
    start_time = time.time()
    model = gp.Model("layout_generation_front desk")
    model.params.NonConvex = 2

    # 初始化 counter_placement 為 None 或者其他適合的預設值
    counter_placement = None

    num_objects = len(obj_params)
    num_unusable_cells = len(unusable_gridcell)

    optgroup_1 = {}

    temp = 0
    for i in range(num_objects):
        if obj_params[i]['group'] == 1:
            optgroup_1.update({temp: obj_params[i]})
            temp += 1

    num_optgroup1 = len(optgroup_1)
    for i in range(num_optgroup1):
        if optgroup_1[i]['name'] == '前櫃檯':
            f = i
        if optgroup_1[i]['name'] == '後櫃檯':
            b = i
        if optgroup_1[i]['name'] == 'ATM':
            atm_index = i

    p, q, s, t, orientation = {}, {}, {}, {}, {}
    x, y, w, h, select, T = {}, {}, {}, {}, {}, {}
    # Binary variables
    for i in range(num_optgroup1):
        for j in range(num_optgroup1):
            if i != j:
                p[i, j] = model.addVar(vtype=GRB.BINARY, name=f"p_{i}_{j}")
                q[i, j] = model.addVar(vtype=GRB.BINARY, name=f"q_{i}_{j}")
        for k in range(num_unusable_cells):
            s[i, k] = model.addVar(vtype=GRB.BINARY, name=f"s_{i}_{k}")
            t[i, k] = model.addVar(vtype=GRB.BINARY, name=f"t_{i}_{k}")
        orientation[i] = model.addVar(vtype=GRB.BINARY, name=f"orientation_{i}")

    # Dimension variables
    for i in range(num_optgroup1):
        x[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"x_{i}")
        y[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"y_{i}")
        w[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"w_{i}")
        h[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"h_{i}")

        for k in range(4):
            select[i, k] = model.addVar(vtype=GRB.BINARY, name=f"select_{i, k}")

        for j in range(num_optgroup1):
            T[i, j] = model.addVar(vtype=GRB.CONTINUOUS, name=f"T_{i, j}")

    # Set objective
    total_area = gp.quicksum(w[i] * h[i] for i in range(num_optgroup1))
    coor = gp.quicksum(x[i] + y[i] for i in range(num_optgroup1))
    model.setObjective((total_area), GRB.MINIMIZE)

    # 計算空間中心點
    center_x = SPACE_WIDTH / 2
    center_y = SPACE_HEIGHT / 2




    # 添加約束來確保ATM位於指定的象限
    if atm_quadrant == 1:
        model.addConstr(x[atm_index] >= center_x, name="ATM in Q1")
        model.addConstr(y[atm_index] >= center_y, name="ATM in Q1")
    elif atm_quadrant == 2:
        model.addConstr(x[atm_index] <= center_x, name="ATM in Q2")
        model.addConstr(y[atm_index] >= center_y, name="ATM in Q2")
    elif atm_quadrant == 3:
        model.addConstr(x[atm_index] <= center_x, name="ATM in Q3")
        model.addConstr(y[atm_index] <= center_y, name="ATM in Q3")
    elif atm_quadrant == 4:
        model.addConstr(x[atm_index] >= center_x, name="ATM in Q4")
        model.addConstr(y[atm_index] <= center_y, name="ATM in Q4")

    # Set constraints for general specifications
    # Connectivity constraint
    for i in range(num_optgroup1):
        if not optgroup_1[i]['connect']:
            pass
        else:
            for j in obj_params[i]['connect']:
                print(f'connect{j}')

                model.addConstr(x[i] + w[i] >= x[j] - SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="Connectivity Constraint 1")
                model.addConstr(y[i] + h[i] >= y[j] - SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="Connectivity Constraint 2")
                model.addConstr(x[j] + w[j] >= x[i] - SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="Connectivity Constraint 3")
                model.addConstr(y[j] + h[j] >= y[i] - SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="Connectivity Constraint 4")
                model.addConstr(0.5 * (w[i] + w[j]) >= T[i, j] + (y[j] - y[i]) - SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="overlap constraint_18")
                model.addConstr(0.5 * (h[i] + h[j]) >= T[i, j] + (x[j] - x[i]) - SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="overlap constraint_19")
                model.addConstr(0.5 * (w[i] + w[j]) >= T[i, j] + (y[i] - y[j]) - SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="overlap constraint_20")
                model.addConstr(0.5 * (h[i] + h[j]) >= T[i, j] + (x[i] - x[j]) - SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="overlap constraint_21")

    # Boundary constraints
    for i in range(num_optgroup1):
        model.addConstr(x[i] + w[i] <= SPACE_WIDTH, name="Boundary constraint for x")
        model.addConstr(y[i] + h[i] <= SPACE_HEIGHT, name="Boundary constraint for y")

    # Fixed border constraint
    for i in range(num_optgroup1):
        if not optgroup_1[i]['fixed_wall']:
            print(f'No fixed wall constraint for object {i}')
        elif optgroup_1[i]['fixed_wall'] == 'any':
            model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
            model.addConstr(
                (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                    i] == 1)
            model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
            model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_1[i]['w_h']) == SPACE_WIDTH))
            model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
            model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_1[i]['w_h']) == SPACE_HEIGHT))
        elif optgroup_1[i]['fixed_wall'] == 'north':
            model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
            model.addConstr(
                (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                    i] == 1)
            model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
            model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_1[i]['w_h']) == SPACE_WIDTH))
            model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
            model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_1[i]['w_h']) == SPACE_HEIGHT))
            model.addConstr(select[i, 2] == 1, name="North border constraint")
        elif optgroup_1[i]['fixed_wall'] == 'south':
            model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
            model.addConstr(
                (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                    i] == 1)
            model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
            model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_1[i]['w_h']) == SPACE_WIDTH))
            model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
            model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_1[i]['w_h']) == SPACE_HEIGHT))
            model.addConstr(select[i, 3] == 1, name="South border constraint")
        elif optgroup_1[i]['fixed_wall'] == 'east':
            model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
            model.addConstr(
                (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                    i] == 1)
            model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
            model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_1[i]['w_h']) == SPACE_WIDTH))
            model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
            model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_1[i]['w_h']) == SPACE_HEIGHT))
            model.addConstr(select[i, 1] == 1, name="East border constraint")
        elif optgroup_1[i]['fixed_wall'] == 'west':
            model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
            model.addConstr(
                (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                    i] == 1)
            model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
            model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_1[i]['w_h']) == SPACE_WIDTH))
            model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
            model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_1[i]['w_h']) == SPACE_HEIGHT))
            model.addConstr(select[i, 0] == 1, name="West border constraint")

    # Non-intersecting with aisle constraint
    for i in range(num_optgroup1):
        for j in range(num_optgroup1):
            if not optgroup_1[i]['connect'] and i != j:
                if [i, j] == [f, b] or [i, j] == [b, f]:
                    model.addConstr((orientation[i] == 0) >> (
                                x[i] + w[i] + COUNTER_SPACING <= x[j] + SPACE_WIDTH * (p[i, j] + q[i, j])),
                                    name="Non-intersecting Constraint 1")
                    model.addConstr((orientation[i] == 1) >> (
                                y[i] + h[i] + COUNTER_SPACING <= y[j] + SPACE_HEIGHT * (1 + p[i, j] - q[i, j])),
                                    name="Non-intersecting Constraint 2")
                    model.addConstr((orientation[i] == 0) >> (
                                x[j] + w[j] + COUNTER_SPACING <= x[i] + SPACE_WIDTH * (1 - p[i, j] + q[i, j])),
                                    name="Non-intersecting Constraint 3")
                    model.addConstr((orientation[i] == 1) >> (
                                y[j] + h[j] + COUNTER_SPACING <= y[i] + SPACE_HEIGHT * (2 - p[i, j] - q[i, j])),
                                    name="Non-intersecting Constraint 4")
                    model.addConstr((orientation[i] == 0) >> (
                                x[i] + w[i] + COUNTER_SPACING >= x[j] - SPACE_WIDTH * (p[i, j] + q[i, j])),
                                    name="Non-intersecting Constraint 1")
                    model.addConstr((orientation[i] == 1) >> (
                                y[i] + h[i] + COUNTER_SPACING >= y[j] - SPACE_HEIGHT * (1 + p[i, j] - q[i, j])),
                                    name="Non-intersecting Constraint 2")
                    model.addConstr((orientation[i] == 0) >> (
                                x[j] + w[j] + COUNTER_SPACING >= x[i] - SPACE_WIDTH * (1 - p[i, j] + q[i, j])),
                                    name="Non-intersecting Constraint 3")
                    model.addConstr((orientation[i] == 1) >> (
                                y[j] + h[j] + COUNTER_SPACING >= y[i] - SPACE_HEIGHT * (2 - p[i, j] - q[i, j])),
                                    name="Non-intersecting Constraint 4")
                else:
                    model.addConstr(x[i] + w[i] + 0.1 <= x[j] + SPACE_WIDTH * (p[i, j] + q[i, j]),
                                    name="Non-intersecting Constraint 1")
                    model.addConstr(y[i] + h[i] + 0.1 <= y[j] + SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                    name="Non-intersecting Constraint 2")
                    model.addConstr(x[j] + w[j] + 0.1 <= x[i] + SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                    name="Non-intersecting Constraint 3")
                    model.addConstr(y[j] + h[j] + 0.1 <= y[i] + SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                    name="Non-intersecting Constraint 4")
            elif i != j:
                model.addConstr(x[i] + w[i] <= x[j] + SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 1")
                model.addConstr(y[i] + h[i] <= y[j] + SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 2")
                model.addConstr(x[j] + w[j] <= x[i] + SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 3")
                model.addConstr(y[j] + h[j] <= y[i] + SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 4")

    # Length constraint
    for i in range(num_optgroup1):
        model.addConstr(w[i] == [min(optgroup_1[i]['w_h']), max(optgroup_1[i]['w_h'])], name="Length Constraint 1")
        model.addConstr(h[i] == [min(optgroup_1[i]['w_h']), max(optgroup_1[i]['w_h'])], name="Height Constraint 2")

    # Unusable grid cell constraint
    for i in range(num_optgroup1):
        for k in range(num_unusable_cells):
            model.addConstr(
                x[i] >= unusable_gridcell[k]['x'] + unusable_gridcell[k]['w'] + 1 - SPACE_WIDTH * (s[i, k] + t[i, k]),
                name="Unusable grid cell 1")
            model.addConstr(unusable_gridcell[k]['x'] >= x[i] + w[i] - SPACE_WIDTH * (1 + s[i, k] - t[i, k]),
                            name="Unusable grid cell 2")
            model.addConstr(y[i] >= unusable_gridcell[k]['y'] + unusable_gridcell[k]['h'] + 1 - SPACE_HEIGHT * (
                        1 - s[i, k] + t[i, k]), name="Unusable grid cell 3")
            model.addConstr(unusable_gridcell[k]['y'] >= y[i] + h[i] - SPACE_HEIGHT * (2 - s[i, k] - t[i, k]),
                            name="Unusable grid cell 4")

    # Orientation constraint
    for i in range(num_optgroup1):
        model.addConstr(w[i] == h[i] * ((max(optgroup_1[i]['w_h']) / min(optgroup_1[i]['w_h'])) * orientation[i] + (
                    min(optgroup_1[i]['w_h']) / max(optgroup_1[i]['w_h'])) * (1 - orientation[i])))

    # Same orientation for front desks
    model.addConstr(orientation[f] == orientation[b])
    model.addConstr((orientation[f] == 1) >> (x[f] == x[b]))
    model.addConstr((orientation[f] == 0) >> (y[f] == y[b]))

    # Constraint for object long side against wall
    for i in range(num_optgroup1):
        for j in range(num_optgroup1):
            if [i, j] == [f, b]:
                model.addConstr((q[i, j] == 1) >> (orientation[i] == 1))
                model.addConstr((q[i, j] == 0) >> (orientation[i] == 0))

    # Optimize the model
    model.optimize()
    end_time = time.time()
    result = {}
    unusable_gridcell2 = {}
    unusable_gridcell2.update(unusable_gridcell)

    # Print objective value and runtime
    if model.status == GRB.OPTIMAL:
        print(f"Runtime: {end_time - start_time} seconds")
        print("Optimal solution found!")
        for i in range(num_optgroup1):
            result.update({i: {'x': x[i].X, 'y': y[i].X, 'w': w[i].X, 'h': h[i].X, 'name': optgroup_1[i]['name']}})
            print(
                f"{result[i]['name']} : x={result[i]['x']}, y={result[i]['y']}, w={result[i]['w']}, h={result[i]['h']}")
            unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X, 'y': y[i].X, 'w': w[i].X, 'h': h[i].X}})
            num_unusable_cells += 1

        # Save space for door opening and lineup space for front counter

        num_unusable_cells = len(unusable_gridcell2)

        for i in range(num_optgroup1):
            if i == b:
                if select[i, 0].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X + w[i].X + COUNTER_SPACING + w[f].X,
                                                                    'y': y[i].X, 'w': LINEUP_SPACING, 'h': h[i].X}})
                    num_unusable_cells += 1
                elif select[i, 1].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {
                        'x': x[i].X - (w[f].X + COUNTER_SPACING + LINEUP_SPACING), 'y': y[i].X, 'w': LINEUP_SPACING,
                        'h': h[i].X}})
                    num_unusable_cells += 1
                elif select[i, 2].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X,
                                                                    'y': y[i].X + h[i].X + COUNTER_SPACING + h[f].X,
                                                                    'w': w[i].X, 'h': LINEUP_SPACING}})
                    num_unusable_cells += 1
                elif select[i, 3].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X, 'y': y[i].X - (
                                h[f].X + COUNTER_SPACING + LINEUP_SPACING), 'w': w[i].X, 'h': LINEUP_SPACING}})
                    num_unusable_cells += 1
            if i == f:
                pass
            else:
                if select[i, 0].X == 1:
                    unusable_gridcell2.update(
                        {num_unusable_cells: {'x': x[i].X + w[i].X, 'y': y[i].X, 'w': OPENDOOR_SPACING, 'h': h[i].X}})
                    num_unusable_cells += 1
                elif select[i, 1].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X - OPENDOOR_SPACING, 'y': y[i].X,
                                                                    'w': OPENDOOR_SPACING, 'h': h[i].X}})
                    num_unusable_cells += 1
                elif select[i, 2].X == 1:
                    unusable_gridcell2.update(
                        {num_unusable_cells: {'x': x[i].X, 'y': y[i].X + h[i].X, 'w': w[i].X, 'h': OPENDOOR_SPACING}})
                    num_unusable_cells += 1
                elif select[i, 3].X == 1:
                    unusable_gridcell2.update({num_unusable_cells: {'x': x[i].X, 'y': y[i].X - OPENDOOR_SPACING,
                                                                    'w': w[i].X, 'h': OPENDOOR_SPACING}})
                    num_unusable_cells += 1

        if select[b, 0].X == 1:
            counter_placement = 'west'
        elif select[b, 1].X == 1:
            counter_placement = 'east'
        elif select[b, 2].X == 1:
            counter_placement = 'north'
        elif select[b, 3].X == 1:
            counter_placement = 'south'

    elif model.status == GRB.INFEASIBLE:
        print("The problem is infeasible. Review your constraints.")
    else:
        print("No solution found.")

        model.computeIIS()
        for c in model.getConstrs():
            if c.IISConstr: print(f'\t{c.constrname}: {model.getRow(c)} {c.Sense} {c.RHS}')
        pass

    return result, unusable_gridcell2, counter_placement


def layout_opt_group2(obj_params, AISLE_SPACE, SPACE_WIDTH, SPACE_HEIGHT, unusable_gridcell):
    # Create a Gurobi model
    start_time = time.time()
    model = gp.Model("layout_generation_front desk")
    model.params.NonConvex = 2

    num_objects = len(obj_params)
    num_unusable_cells = len(unusable_gridcell)

    optgroup_2 = {}

    temp = 0
    for i in range(num_objects):
        if obj_params[i]['group'] == 2:
            optgroup_2.update({temp: obj_params[i]})
            temp += 1
    num_optgroup2 = len(optgroup_2)

    for i in range(num_optgroup2):
        if optgroup_2[i]['name'] == '貨架區':
            shelf = i
            # print(shelf)

    p, q, s, t, orientation = {}, {}, {}, {}, {}
    x, y, w, h, select, T = {}, {}, {}, {}, {}, {}
    # Binary variables
    for i in range(num_optgroup2):
        for j in range(num_optgroup2):
            if i != j:
                p[i, j] = model.addVar(vtype=GRB.BINARY, name=f"p_{i}_{j}")
                q[i, j] = model.addVar(vtype=GRB.BINARY, name=f"q_{i}_{j}")
        for k in range(num_unusable_cells):
            s[i, k] = model.addVar(vtype=GRB.BINARY, name=f"s_{i}_{k}")
            t[i, k] = model.addVar(vtype=GRB.BINARY, name=f"t_{i}_{k}")
        orientation[i] = model.addVar(vtype=GRB.BINARY, name=f"orientation_{i}")

    # Dimension variables
    for i in range(num_optgroup2):
        x[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"x_{i}")
        y[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"y_{i}")
        w[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"w_{i}")
        h[i] = model.addVar(vtype=GRB.CONTINUOUS, name=f"h_{i}")

        for k in range(4):
            select[i, k] = model.addVar(vtype=GRB.BINARY, name=f"select_{i, k}")

        for j in range(num_optgroup2):
            T[i, j] = model.addVar(vtype=GRB.CONTINUOUS, name=f"T_{i, j}")

    # Set objective
    # model.setObjective(gp.quicksum(w[i]*h[i] for i in range(num_optgroup2)), GRB.MINIMIZE)
    # model.setParam('TimeLimit', 1800)
    model.setObjective(w[shelf] * h[shelf], GRB.MAXIMIZE)
    # Set constraints for general specifications
    # Connectivity constraint
    for i in range(num_optgroup2):
        if not optgroup_2[i]['connect']:
            pass
        else:
            for j in optgroup_2[i]['connect']:
                print(f'Object {i} and Object {j} should be connected')
                model.addConstr(x[i] + w[i] >= x[j] - SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="Connectivity Constraint 1")
                model.addConstr(y[i] + h[i] >= y[j] - SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="Connectivity Constraint 2")
                model.addConstr(x[j] + w[j] >= x[i] - SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="Connectivity Constraint 3")
                model.addConstr(y[j] + h[j] >= y[i] - SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="Connectivity Constraint 4")
                model.addConstr(0.5 * (w[i] + w[j]) >= T[i, j] + (y[j] - y[i]) - SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="overlap constraint_18")
                model.addConstr(0.5 * (h[i] + h[j]) >= T[i, j] + (x[j] - x[i]) - SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="overlap constraint_19")
                model.addConstr(0.5 * (w[i] + w[j]) >= T[i, j] + (y[i] - y[j]) - SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="overlap constraint_20")
                model.addConstr(0.5 * (h[i] + h[j]) >= T[i, j] + (x[i] - x[j]) - SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="overlap constraint_21")

    # Boundary constraints
    for i in range(num_optgroup2):
        model.addConstr(x[i] + w[i] <= SPACE_WIDTH, name="Boundary constraint for x")
        model.addConstr(y[i] + h[i] <= SPACE_HEIGHT, name="Boundary constraint for y")

    # Fixed border constraint with layers
    for i in range(num_optgroup2):
        if not optgroup_2[i]['fixed_wall']:
            print(f'No fixed wall constraint for object {i}')
        else:
            allowed_layers = optgroup_2[i].get('layers', [])
            if optgroup_2[i]['fixed_wall'] == 'any':
                for layer in allowed_layers:
                    # Adjust constraints based on the specific layer
                    if layer == 'window':
                        # Constraints for window layer
                        model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                        model.addConstr(
                            (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                                i] == 1)
                        model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                        model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                        model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                        model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
                    elif layer == 'solid_wall':
                        # Constraints for solid_wall layer
                        model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                        model.addConstr(
                            (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                                i] == 1)
                        model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                        model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                        model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                        model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
            elif optgroup_2[i]['fixed_wall'] == 'north':
                model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                # 限制長邊靠牆
                model.addConstr(
                    (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                        i] == 1)
                model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
                model.addConstr(select[i, 2] == 1, name="North border constraint")
            elif optgroup_2[i]['fixed_wall'] == 'south':
                model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                # 限制長邊靠牆
                model.addConstr(
                    (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                        i] == 1)
                model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
                model.addConstr(select[i, 3] == 1, name="South border constraint")
            elif optgroup_2[i]['fixed_wall'] == 'east':
                model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                # 限制長邊靠牆
                model.addConstr(
                    (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                        i] == 1)
                model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
                model.addConstr(select[i, 1] == 1, name="East border constraint")
            elif optgroup_2[i]['fixed_wall'] == 'west':
                model.addConstr(select[i, 0] + select[i, 1] + select[i, 2] + select[i, 3] == 1)
                # 限制長邊靠牆
                model.addConstr(
                    (select[i, 0] + select[i, 1]) * (1 - orientation[i]) + (select[i, 2] + select[i, 3]) * orientation[
                        i] == 1)
                model.addConstr((select[i, 0] == 1) >> (x[i] == 0))
                model.addConstr((select[i, 1] == 1) >> (x[i] + min(optgroup_2[i]['w_h']) == SPACE_WIDTH))
                model.addConstr((select[i, 2] == 1) >> (y[i] == 0))
                model.addConstr((select[i, 3] == 1) >> (y[i] + min(optgroup_2[i]['w_h']) == SPACE_HEIGHT))
                model.addConstr(select[i, 0] == 1, name="West border constraint")

    # Non-intersecting with aisle constraint
    for i in range(num_optgroup2):
        for j in range(num_optgroup2):
            if not optgroup_2[i]['connect'] and i != j:
                model.addConstr(x[i] + w[i] + AISLE_SPACE <= x[j] + SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 1")
                model.addConstr(y[i] + h[i] + AISLE_SPACE <= y[j] + SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 2")
                model.addConstr(x[j] + w[j] + AISLE_SPACE <= x[i] + SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 3")
                model.addConstr(y[j] + h[j] + AISLE_SPACE <= y[i] + SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 4")
            elif i != j:
                model.addConstr(x[i] + w[i] <= x[j] + SPACE_WIDTH * (p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 1")
                model.addConstr(y[i] + h[i] <= y[j] + SPACE_HEIGHT * (1 + p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 2")
                model.addConstr(x[j] + w[j] <= x[i] + SPACE_WIDTH * (1 - p[i, j] + q[i, j]),
                                name="Non-intersecting Constraint 3")
                model.addConstr(y[j] + h[j] <= y[i] + SPACE_HEIGHT * (2 - p[i, j] - q[i, j]),
                                name="Non-intersecting Constraint 4")

    # Length constraint
    for i in range(num_optgroup2):
        if i != shelf:
            model.addConstr(w[i] == [min(optgroup_2[i]['w_h']), max(optgroup_2[i]['w_h'])], name="Length Constraint 1")
            model.addConstr(h[i] == [min(optgroup_2[i]['w_h']), max(optgroup_2[i]['w_h'])], name="Height Constraint 2")

    model.addConstr(w[shelf] <= SPACE_WIDTH, name="Shelf area 1")
    model.addConstr(h[shelf] <= SPACE_HEIGHT, name="Shelf area2")

    # Unusable grid cell constraint
    for i in range(num_optgroup2):
        for k in range(num_unusable_cells):
            model.addConstr(
                x[i] >= unusable_gridcell[k]['x'] + unusable_gridcell[k]['w'] + 1 - SPACE_WIDTH * (s[i, k] + t[i, k]),
                name="Unusable grid cell 1")
            model.addConstr(unusable_gridcell[k]['x'] >= x[i] + w[i] - SPACE_WIDTH * (1 + s[i, k] - t[i, k]),
                            name="Unusable grid cell 2")
            model.addConstr(y[i] >= unusable_gridcell[k]['y'] + unusable_gridcell[k]['h'] + 1 - SPACE_HEIGHT * (
                        1 - s[i, k] + t[i, k]), name="Unusable grid cell 3")
            model.addConstr(unusable_gridcell[k]['y'] >= y[i] + h[i] - SPACE_HEIGHT * (2 - s[i, k] - t[i, k]),
                            name="Unusable grid cell 4")
    # Orientation constraint
    for i in range(num_optgroup2):
        if i != shelf:
            model.addConstr(w[i] == h[i] * ((max(optgroup_2[i]['w_h']) / min(optgroup_2[i]['w_h'])) * orientation[i]
                                            + (min(optgroup_2[i]['w_h']) / max(optgroup_2[i]['w_h'])) * (
                                                        1 - orientation[i])))

    # Optimize the model
    model.optimize()
    end_time = time.time()
    result = {}
    shelf_area = {}

    # Print objective value and runtime
    if model.status == GRB.OPTIMAL:
        print(f"Runtime: {end_time - start_time} seconds")
        print("Optimal solution found!")
        for i in range(num_optgroup2):
            result.update({i: {'x': x[i].X, 'y': y[i].X, 'w': w[i].X, 'h': h[i].X, 'name': optgroup_2[i]['name']}})
            print(
                f"{result[i]['name']} : x={result[i]['x']}, y={result[i]['y']}, w={result[i]['w']}, h={result[i]['h']}")
            if i == shelf:
                shelf_area.update({'x': x[i].X, 'y': y[i].X, 'w': w[i].X, 'h': h[i].X})

    elif model.status == GRB.INFEASIBLE:
        print("The problem is infeasible. Review your constraints.")
    else:
        print("No solution found.")

        model.computeIIS()
        for c in model.getConstrs():
            if c.IISConstr: print(f'\t{c.constrname}: {model.getRow(c)} {c.Sense} {c.RHS}')
        pass
    return result, shelf_area, shelf


def shelf_opt(shelf_area, shelf_spec, counter_placement):
    x, y = shelf_area['x'], shelf_area['y']
    max_width = int(shelf_area['w'])
    max_height = int(shelf_area['h'])
    if counter_placement == 'west':
        shelf_placement = KPtest.knapsack_placement(max_width, max_height, shelf_spec, shelf_height)
        shelf_placement = KPtest.add_FF(shelf_placement, shelf_spec, max_width)
    elif counter_placement == 'east':
        shelf_placement = KPtest.knapsack_placement(max_width, max_height, shelf_spec, shelf_height)
        shelf_placement = KPtest.add_FF(shelf_placement, shelf_spec, max_width)
        shelf_placement = flip.vertical(max_width, shelf_placement)
    elif counter_placement == 'north':
        shelf_placement = KPtest.knapsack_placement(max_height, max_width, shelf_spec, shelf_height)
        shelf_placement = KPtest.add_FF(shelf_placement, shelf_spec, max_width)
        shelf_placement = flip.cw(max_height, max_width, shelf_placement)
    elif counter_placement == 'south':
        shelf_placement = KPtest.knapsack_placement(max_height, max_width, shelf_spec, shelf_height)
        shelf_placement = KPtest.add_FF(shelf_placement, shelf_spec, max_width)
        shelf_placement = flip.ccw(max_height, max_width, shelf_placement)
    num_shelf = len(shelf_placement)

    for i in range(num_shelf):
        shelf_placement[i]['x'] = shelf_placement[i]['x'] + x
        shelf_placement[i]['y'] = shelf_placement[i]['y'] + y
    num_shelf = len(shelf_placement)

    for i in range(num_shelf):
        if i == 0:
            shelf_name = 'FF'
            shelf_placement[i]['name'] = shelf_name
        else:
            shelf_name = f"{int(shelf_placement[i]['w'])}x{int(shelf_placement[i]['h'])}"
            shelf_placement[i]['name'] = shelf_name
    for i in range(num_shelf):
        print(
            f"{shelf_placement[i]['name']} : x={shelf_placement[i]['x']}, y={shelf_placement[i]['y']}, w={shelf_placement[i]['w']}, h={shelf_placement[i]['h']}")

    return shelf_placement


def layout_plot(obj_params, result1, result2, shelf_placement, unusable_gridcell):
    num_objects = len(obj_params)
    # Plot opt_group1
    data = result1

    # Define total space dimensions
    total_space = {'width': SPACE_WIDTH, 'height': SPACE_HEIGHT}

    # Create a new figure
    plt.figure(figsize=(8, 8))
    matplotlib.rcParams['font.family'] = ['Heiti TC']
    # Plot total space
    plt.gca().add_patch(
        plt.Rectangle((0, 0), SPACE_WIDTH, SPACE_HEIGHT, fill=None, edgecolor='blue', label='Total Space'))

    optgroup_1 = {}

    temp = 0
    for i in range(num_objects):
        if obj_params[i]['group'] == 1:
            optgroup_1.update({temp: obj_params[i]})
            temp += 1
    num_optgroup1 = len(optgroup_1)
    object_name = {}
    for i in range(num_optgroup1):
        object_name.update({i: optgroup_1[i]['name']})

    # Plot each object
    for object_id, object_info in data.items():
        x = object_info['x']
        y = object_info['y']
        w = object_info['w']
        h = object_info['h']

        plt.gca().add_patch(plt.Rectangle((x, y), w, h, fill=None, edgecolor='black', label=object_name[object_id]))
        plt.text(x + w / 2, y + h / 2, object_name[object_id], ha='center', va='center', color='red', fontsize=12)

    # Plot opt_group2
    data = result2

    optgroup_2 = {}

    temp = 0
    for i in range(num_objects):
        if obj_params[i]['group'] == 2:
            optgroup_2.update({temp: obj_params[i]})
            temp += 1
    num_optgroup2 = len(optgroup_2)
    object_name = {}
    for i in range(num_optgroup2):
        object_name.update({i: optgroup_2[i]['name']})

    # Plot each object
    for object_id, object_info in data.items():
        x = object_info['x']
        y = object_info['y']
        w = object_info['w']
        h = object_info['h']
        if object_id == 0:
            '''
            plt.gca().add_patch(plt.Rectangle((x, y), w, h, fill=None, edgecolor='black', label=object_name[object_id]))
            print(f'The area of shelf area = {w}x{h}')
            plt.text(x + w/2, y + h/2, object_name[object_id], ha='center', va='center', color='red', fontsize=12)
            '''
            pass
        else:
            plt.gca().add_patch(plt.Rectangle((x, y), w, h, fill=None, edgecolor='black', label=object_name[object_id]))
            plt.text(x + w / 2, y + h / 2, object_name[object_id], ha='center', va='center', color='red', fontsize=12)

    # Plot shelf area
    data = shelf_placement

    num_shelf = len(shelf_placement)
    object_name = {}
    for i in range(num_shelf):
        if i == 0:
            shelf_name = 'FF'
            object_name.update({i: shelf_name})
        else:
            shelf_name = f"{int(shelf_placement[i]['w'])}x{int(shelf_placement[i]['h'])}"
            object_name.update({i: shelf_name})

    # Plot each object
    for object_id, object_info in data.items():
        x = object_info['x']
        y = object_info['y']
        w = object_info['w']
        h = object_info['h']

        plt.gca().add_patch(plt.Rectangle((x, y), w, h, fill=None, edgecolor='black', label=object_name[object_id]))
        plt.text(x + w / 2, y + h / 2, object_name[object_id], ha='center', va='center', color='red', fontsize=12)

    # Plot obstacle
    # Parameters adaptation
    obstacle_positions = [(unusable_gridcell[k]['x'], unusable_gridcell[k]['y']) for k in unusable_gridcell]
    obstacle_dimensions = [(unusable_gridcell[k]['w'], unusable_gridcell[k]['h']) for k in unusable_gridcell]
    for k, (x_u, y_u) in enumerate(obstacle_positions):
        w_u, h_u = obstacle_dimensions[k]
        plt.gca().add_patch(plt.Rectangle((x_u, y_u), w_u, h_u, fill=None, edgecolor='red', label='X'))
        plt.text(x_u + w_u / 2, y_u + h_u / 2, 'x', ha='center', va='center', color='red', fontsize=8)
    # Set plot limits and labels
    plt.xlim(0, SPACE_WIDTH)
    plt.ylim(0, SPACE_HEIGHT)
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('Space Layout')

    # Show plot
    plt.grid(True)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.show()


if __name__ == '__main__':
    doc_path = 'result1.dxf'  # doc 是字串

    # 獲取空間的邊界值
    min_x, min_y, max_x, max_y = get_dxf_bounds(doc_path)

    # 計算 DXF 檔案中所有實體的中點
    center_x, center_y = calculate_midpoint(min_x, min_y, max_x, max_y)

    # 打印出計算的中點
    print(f"DXF 檔案中的中點位置：({center_x}, {center_y})")

    # 使用 get_door 函式來獲取門的資訊
    door_segments = get_door(doc_path)

    # 確保門的資料是存在的
    if door_segments:
        # 取第一個門段的起始點
        door_x, door_y = door_segments[0][0], door_segments[0][1]

        # 計算門的位置象限
        door_quadrant = determine_quadrant(door_x, door_y, center_x, center_y)

        # 打印出門的位置象限
        print(f"門的位置：({door_x}, {door_y}) 屬於象限: {door_quadrant}")

    # 使用 get_feasible_area 獲得 `feasible_area` 和 `poly_feasible`
    unusable_gridcell, min_x, max_x, min_y, max_y, poly_feasible = get_feasible_area.feasible_area(doc_path)

    # 確保正確定義 `feasible`
    points = re.findall(r'\d+\s\d+', str(poly_feasible).replace("POLYGON ", ""))
    feasible = [tuple(map(int, point.split())) for point in points]

    SPACE_WIDTH, SPACE_HEIGHT = max_x - min_x + 1, max_y - min_y + 1
    AISLE_SPACE = 100
    COUNTER_SPACING = 110
    OPENDOOR_SPACING = 110
    LINEUP_SPACING = 160

    # 定義 shelf_spec 變數
    shelf_spec = [132, 223, 314, 405, 496, 587, 678, 91, 182, 273, 364, 455, 546]  # 假設的數值，可根據需求調整
    shelf_height = [78]

    # 定義參數和變量
    obj_params = {
        0: {'group': 2, 'w_h': [SPACE_WIDTH, SPACE_HEIGHT], 'connect': [], 'fixed_wall': 'none', 'name': '貨架區'},
        1: {'group': 1, 'w_h': [465, 66], 'connect': [], 'fixed_wall': 'none', 'name': '前櫃檯'},
        2: {'group': 1, 'w_h': [598, 66], 'connect': [], 'fixed_wall': 'any', 'name': '後櫃檯', 'layers': ['window']},
        3: {'group': 1, 'w_h': [365, 270], 'connect': [], 'fixed_wall': 'any', 'name': 'WI',
            'layers': ['solid_wall', 'window']},
        4: {'group': 2, 'w_h': [90, 66], 'connect': [], 'fixed_wall': 'none', 'name': '雙溫櫃'},
        5: {'group': 2, 'w_h': [90, 66], 'connect': [], 'fixed_wall': 'none', 'name': '單溫櫃'},
        6: {'group': 2, 'w_h': [90, 66], 'connect': [], 'fixed_wall': 'none', 'name': 'OC'},
        7: {'group': 1, 'w_h': [310, 225], 'connect': [], 'fixed_wall': 'any', 'name': 'RI',
            'layers': ['solid_wall', 'window']},
        8: {'group': 1, 'w_h': [95, 59], 'connect': [], 'fixed_wall': 'any', 'name': 'EC',
            'layers': ['solid_wall', 'window']},
        9: {'group': 1, 'w_h': [190, 90], 'connect': [], 'fixed_wall': 'any', 'name': '子母櫃'},
        10: {'group': 1, 'w_h': [100, 85], 'connect': [], 'fixed_wall': 'any', 'name': 'ATM',
             'layers': ['solid_wall', 'window']},
        11: {'group': 1, 'w_h': [83, 64], 'connect': [], 'fixed_wall': 'any', 'name': '影印',
             'layers': ['solid_wall', 'window']},
        12: {'group': 1, 'w_h': [80, 55], 'connect': [], 'fixed_wall': 'any', 'name': 'KIOSK',
             'layers': ['solid_wall', 'window']}
    }

    result1, unusable_gridcell2, counter_placement = layout_opt_group1(
        obj_params, COUNTER_SPACING, SPACE_WIDTH, SPACE_HEIGHT, OPENDOOR_SPACING, LINEUP_SPACING, unusable_gridcell,
        doc_path, center_x, center_y  # 傳遞計算得到的中點
    )

    result2, shelf_area, shelf_id = layout_opt_group2(
        obj_params, AISLE_SPACE, SPACE_WIDTH, SPACE_HEIGHT, unusable_gridcell2
    )

    result2.pop(shelf_id)
    shelf_placement = shelf_opt(shelf_area, shelf_spec, counter_placement)

    # 整合結果
    result = {}
    values = list(result1.values()) + list(result2.values()) + list(shelf_placement.values())
    result = {i: values[i] for i in range(len(values))}

    # 畫出結果並保存到 DXF 文件
    dxf_manipulation.draw_dxf(result, feasible)
    layout_plot(obj_params, result1, result2, shelf_placement, unusable_gridcell)
