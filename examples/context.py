import json
from pathlib import Path

def load():
    return json.loads((Path(__file__).with_name("context.json")).read_text())

def run():
    from researchmesh.service import ResearchMesh
    data = load()
    with ResearchMesh() as app:
        app.sources.register('lab','合成研究登记',10)
        app.sources.snapshot('lab-1','lab',1,data['records'],0)
        preview = app.releases.preview()
        app.releases.freeze('network-input',preview['digest'],'publisher')
        app.sources.register('extra','合成新增来源',20)
        duplicates = [row for row in data['records'] if row['data']['year'] == 2026][:3]
        app.sources.snapshot('extra-1','extra',1,duplicates,0)
        for row in duplicates:
            left, right = 'lab:'+row['id'], 'extra:'+row['id']
            match = app.graph.preview(left,right)
            app.graph.decide('same-'+row['id'],left,right,'merge',match['digest'],'reviewer','同一合成成果的来源副本')
        second = app.releases.preview()
        app.releases.freeze('expanded-input',second['digest'],'publisher')
        assert len(app.graph.clusters()) == len(data['records'])
        return {'ok': app.quality.verify()['verified'], 'records': len(data['records'])}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
