import os 

flist = []
for root, _, files in os.walk('capture/20250816_100250'):
    for file in files:
        flist.append(os.path.join(root, file)+'\n')
flist.sort()


with open('file_list.txt','w') as fp:
    fp.writelines(flist)