# -*t coding: utf-8 -*-
import torch
import torch.nn as nn
from transformers import AutoModel
import numpy as np
import torch.nn.functional as F
from math import sqrt


class CNNBert(nn.Module):
    def __init__(self, emb_size):
        super(CNNBert, self).__init__()
        filter_sizes = [2, 3, 4]
        num_filters = 4
        self.conv1 = nn.ModuleList([nn.Conv2d(3, num_filters, (K, emb_size)) for K in filter_sizes])
        self.dropout = nn.Dropout(0.1)
        self.fc = nn.Linear(len(filter_sizes) * num_filters, 768)

    def forward(self, bert_in):
        x = (bert_in[7], bert_in[9], bert_in[12])
        x = torch.stack(x, dim=1)
        x = [F.relu(conv(x)).squeeze(3) for conv in self.conv1]
        x = [F.max_pool1d(i, i.size(2)).squeeze(2) for i in x]
        x = torch.cat(x, 1)
        x = self.dropout(x)
        x = self.fc(x)
        return x


class AttentionLayer(nn.Module):
    def __init__(self):
        super(AttentionLayer, self).__init__()
        self.q_linear = nn.Linear(768, 768, bias=False)
        self.k_linear = nn.Linear(768, 768, bias=False)
        self.v_linear = nn.Linear(768, 768, bias=False)
        self._norm_fact = 1 / sqrt(768)

    def forward(self, b_in, mask):
        q = self.q_linear(b_in)
        k = self.k_linear(b_in)
        v = self.v_linear(b_in)

        mask = mask.unsqueeze(2)
        attention = torch.bmm(q, k.transpose(1, 2)) * self._norm_fact
        attention = attention.masked_fill(mask == 0, float('-inf'))
        attention = F.softmax(attention, dim=-1)
        attention = torch.bmm(attention, v)
        pre = attention[:, 0, :]
        return pre


    # mask = mask.unsqueeze(2)
    # att_w = att_w.masked_fill(mask == 0, float('-inf'))
    # att_w = F.softmax(att_w, dim=1)


class Model(nn.Module):
    def __init__(self, name, temp=0.2, config=None, cnnl=None, cnnr=None):
        super(Model, self).__init__()
        self.model = AutoModel.from_pretrained(name, config)
        self.temp = temp
        self.drop = nn.Dropout(0.3)
        self.fc1 = nn.Linear(768 * 4, 768)
        self.fc2 = nn.Linear(768, 6)

        # self.mix_fc = nn.Linear(768, 6)
        # self.mix_fc1 = nn.Linear(768, 6)
        # self.des_fc = nn.Linear(768, 6)

        self.au_task_fc1 = nn.Linear(768 * 2, 768)
        self.au_task_fc2 = nn.Linear(768, 5)

        self.supmlp1 = nn.Sequential(nn.Linear(768 * 2, 768), nn.ReLU(inplace=True), nn.Linear(768, 192))
        self.supmlp2 = nn.Sequential(nn.Linear(768 * 2, 768), nn.ReLU(inplace=True), nn.Linear(768, 192))
        self.ori_att = nn.Sequential(nn.Linear(768, 384), nn.Tanh(), nn.Linear(384, 1, bias=False))
        self.re_att = nn.Sequential(nn.Linear(768, 384), nn.Tanh(), nn.Linear(384, 1, bias=False))
        self.cnnl = cnnl
        self.cnnr = cnnr
        # self.ori_word_atten = nn.Linear(768, 384)
        # self.ori_tanh = nn.Tanh()
        # self.ori_word_weight = nn.Linear(384, 1, bias=False)
        #
        # self.re_word_atten = nn.Linear(768, 384)
        # self.re_tanh = nn.Tanh()
        # self.re_word_weight = nn.Linear(384, 1, bias=False)

        # self.des_word_atten = nn.Linear(768, 384)
        # self.des_tanh = nn.Tanh()
        # self.des_word_weight = nn.Linear(384, 1, bias=False)
        # self.cnnber = CNNBert(768)



    def generate_sen_pre(self, sen, tp):
        # s_ids = kwargs['s_sen']['input_ids']
        # s_attention_mask = kwargs['s_sen']['attention_mask']
        # s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
        # s_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
        # return s_pre
        # ids = sen['input_ids']
        # attention_mask = sen['attention_mask']
        bert_output = self.model(sen['input_ids'], attention_mask=sen['attention_mask'], output_hidden_states=True)
        sen = self.get_sen_att(sen, bert_output, tp, sen['attention_mask'])
        return sen, bert_output

    # original
    def forward(self, x1, **kwargs):
        input_ids = x1['input_ids']
        # batch_size = input_ids.shape[0]
        attention_mask = x1['attention_mask']
        bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
        ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
        ocnn_sen_pre = self.cnnl(bert_output[2])
        if self.training:
            # Obtain the representation vector for the classification learning branch
            # r_ids = kwargs['r_sen']['input_ids']
            # r_attention_mask = kwargs['r_sen']['attention_mask']
            # r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
            # re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
            re_sen_pre, r_bert_out = self.generate_sen_pre(kwargs['r_sen'], 're')
            rcnn_sen_pre = self.cnnr(r_bert_out[2])
            # Get the representation vector for the auxiliary task
            # s_ids = kwargs['s_sen']['input_ids']
            # s_attention_mask = kwargs['s_sen']['attention_mask']
            # s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
            # ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
            ausec_sen_pre, a_bert_out = self.generate_sen_pre(kwargs['s_sen'], 'ori')
            acnn_sen_pre = self.cnnl(a_bert_out[2])

            ori_sen_pre = torch.cat((ori_sen_pre, ocnn_sen_pre), dim=1)
            re_sen_pre = torch.cat((re_sen_pre, rcnn_sen_pre), dim=1)

            # ori_sen_pre = self.drop(ori_sen_pre)
            # re_sen_pre = self.drop(re_sen_pre)
            # Splice the representation vectors of both branches
            mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)

            sup_out1 = self.supmlp1(ori_sen_pre)
            sup_out1 = F.normalize(sup_out1, dim=1)

            # sup_out2 = self.supmlp2(re_sen_pre)
            # sup_out2 = F.normalize(sup_out2, dim=1)
            #123
            main_output = self.fc1(mixed_feature)
            # main_output = nn.ReLU(inplace=True)(main_output)
            # sup_out1 = self.supmlp1(main_output)

            main_output = nn.ReLU(inplace=True)(main_output)
            main_output = self.drop(main_output)
            main_output = self.fc2(main_output)

            # sup_out1 = F.normalize(sup_out1, dim=1)

            ausec_sen_pre = torch.cat((ausec_sen_pre, acnn_sen_pre), dim=1)
            au_output1 = self.au_task_fc1(ausec_sen_pre)
            au_output1 = nn.ReLU(inplace=True)(au_output1)
            au_output1 = self.drop(au_output1)
            au_output1 = self.au_task_fc2(au_output1)

            return main_output, au_output1, sup_out1

        re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
        rcnn_sen_pre = self.cnnr(bert_output[2])
        #
        ori_sen_pre = torch.cat((ori_sen_pre, ocnn_sen_pre), dim=1)
        re_sen_pre = torch.cat((re_sen_pre, rcnn_sen_pre), dim=1)

        mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
        mixed_feature = self.fc1(mixed_feature)
        # sup_out1 = self.supmlp1(mixed_feature)
        mixed_feature = nn.ReLU(inplace=True)(mixed_feature)
        mixed_feature = self.fc2(mixed_feature)
        return mixed_feature

    # forward for i-mix
    # def forward(self, x1, **kwargs):
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         # for i-mix
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_imix = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #         # bert_output_imix = self.drop(bert_output_imix)
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, ori_sen_pre_imix], dim=0)
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #         # mix_loss = (lam * criterion(mix_logits, mix_labels) + (1. - lam) * criterion(mix_logits, labels_aux)).mean()
    #
    #
    #         # Obtain the representation vector for the classification learning branch
    #         re_sen_pre = self.generate_sen_pre(sen=kwargs['r_sen'], tp='re')
    #         # r_ids = kwargs['r_sen']['input_ids']
    #         # r_attention_mask = kwargs['r_sen']['attention_mask']
    #         # r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         # re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #
    #         # Get the representation vector for the auxiliary task
    #         ausec_sen_pre = self.generate_sen_pre(sen=kwargs['s_sen'], tp='ori')
    #         # s_ids = kwargs['s_sen']['input_ids']
    #         # s_attention_mask = kwargs['s_sen']['attention_mask']
    #         # s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         # ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature




    # left imix & left cnn for right space
    # def forward(self, x1, **kwargs): # dataset_train_limix_rspace_cnn
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #     cnn_out = self.cnnber(bert_output[2])
    #     if self.training:
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_imix = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, ori_sen_pre_imix], dim=0)
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #         re_sen_pre = self.generate_sen_pre(sen=kwargs['r_sen'], tp='re')
    #         ausec_sen_pre = self.generate_sen_pre(sen=kwargs['s_sen'], tp='ori')
    #
    #         # for CNN
    #         # cnn_out = self.cnnber(bert_output[2])
    #         cnn_mean = self.generate_hidden_mean(cnn_out, kwargs['ori_label'])
    #         re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         re_sen_pre = None
    #         for i in range(cnn_out.shape[0]):
    #             gen_example = cnn_out[i] - cnn_mean[kwargs['ori_label'][i].item()] + re_mean[kwargs['re_label'][i].item()]
    #             if re_sen_pre is None:
    #                 re_sen_pre = gen_example.unsqueeze(0)
    #             else:
    #                 re_sen_pre = torch.cat([re_sen_pre, gen_example.unsqueeze(0)], 0)
    #
    #         ori_sen_pre = torch.cat((ori_sen_pre, cnn_out), dim=1)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
    #     # ori_sen_pre = ori_sen_pre + cnn_out
    #     ori_sen_pre = torch.cat((ori_sen_pre, cnn_out), dim=1)
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature





    # for feature space aug

    def generate_hidden_mean(self, pre, label):
        unique_label = torch.unique(label)
        mean_dict = dict()
        for i in range(unique_label.shape[0]):
            idx_t2n = label.numpy()
            index = np.argwhere(idx_t2n == unique_label[i].item())
            index = torch.tensor(index).squeeze(1).to(device=pre.device)
            select_vector = pre.index_select(0, index)
            mean_value = torch.mean(select_vector, 0)
            mean_dict[unique_label[i].item()] = mean_value
        return mean_dict

    # forward for space aug
    # def forward(self, x1, **kwargs):
    #
    #     input_ids = x1['input_ids']
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #
    #         ori_mean = self.generate_hidden_mean(ori_sen_pre, kwargs['ori_label'])
    #         re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         re_sen_pre = None
    #         for i in range(ori_sen_pre.shape[0]):
    #             gen_example = ori_sen_pre[i] - ori_mean[kwargs['ori_label'][i].item()] + re_mean[kwargs['re_label'][i].item()]
    #             if re_sen_pre is None:
    #                 re_sen_pre = gen_example.unsqueeze(0)
    #             else:
    #                 re_sen_pre = torch.cat([re_sen_pre, gen_example.unsqueeze(0)], 0)
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature

    # for imix and space aug
    def generate_new_example(self, ori_sen_pre, ori_mean, re_mean, ori_label, re_label):
        re_sen_pre = None
        for i in range(ori_sen_pre.shape[0]):
            gen_example = ori_sen_pre[i] - ori_mean[ori_label[i].item()] + re_mean[
                re_label[i].item()]
            if re_sen_pre is None:
                re_sen_pre = gen_example.unsqueeze(0)
            else:
                re_sen_pre = torch.cat([re_sen_pre, gen_example.unsqueeze(0)], 0)
        return re_sen_pre

    # def forward(self, x1, **kwargs):
    #
    #     input_ids = x1['input_ids']
    #     attention_mask = x1['attention_mask']
    #     batch_size = input_ids.shape[0]
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #
    #
    #         # for i-mix
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_imix = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #
    #
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #
    #         ori_imix_mean1 = self.generate_hidden_mean(ori_sen_pre_mix, kwargs['ori_label'])
    #         ori_imix_mean2 = self.generate_hidden_mean(ori_sen_pre_imix, kwargs['ori_label'])
    #
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #         re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         re_sen_pre1 = self.generate_new_example(ori_sen_pre_mix, ori_imix_mean1, re_mean, kwargs['ori_label'], kwargs['re_label'])
    #         re_sen_pre2 = self.generate_new_example(ori_sen_pre_imix, ori_imix_mean2, re_mean, kwargs['ori_label'], kwargs['re_label'])
    #
    #
    #         ori_sen_pre_mix = self.drop(ori_sen_pre_mix)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #         re_sen_pre1 = self.drop(re_sen_pre1)
    #         re_sen_pre2 = self.drop(re_sen_pre2)
    #
    #         # Splice the representation vectors of both branches
    #         mixed_feature1 = 2 * torch.cat((kwargs['l'] * ori_sen_pre_mix, (1 - kwargs['l']) * re_sen_pre1), dim=1)
    #         mixed_feature2 = 2 * torch.cat((kwargs['l'] * ori_sen_pre_imix, (1 - kwargs['l']) * re_sen_pre2), dim=1)
    #
    #         mixed_feature1, labels_aux, lam = self.imix(mixed_feature1, kwargs['mix_alpha'])
    #
    #         temp = torch.cat([mixed_feature1, mixed_feature2], dim=0)
    #
    #         main_output = self.fc1(temp)
    #         main_output = self.fc(main_output)
    #
    #         main_output = nn.functional.normalize(main_output, dim=1)
    #         main_output1, main_output2 = main_output[:batch_size], main_output[batch_size:]
    #         mix_logits = main_output1.mm(main_output2.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return au_output1, mix_logits, mix_labels, labels_aux, lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature


    # def forward(self, x1, **kwargs): # left imix & right space aug
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         # for i-mix
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_imix = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #         # bert_output_imix = self.drop(bert_output_imix)
    #
    #
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, ori_sen_pre_imix], dim=0)
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #
    #         ori_mean = self.generate_hidden_mean(ori_sen_pre_mix, kwargs['ori_label'])
    #         re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         re_sen_pre = None
    #         for i in range(ori_sen_pre_mix.shape[0]):
    #             gen_example = ori_sen_pre_mix[i] - ori_mean[kwargs['ori_label'][i].item()] + re_mean[
    #                 kwargs['re_label'][i].item()]
    #             if re_sen_pre is None:
    #                 re_sen_pre = gen_example.unsqueeze(0)
    #             else:
    #                 re_sen_pre = torch.cat([re_sen_pre, gen_example.unsqueeze(0)], 0)
    #
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre_mix)
    #         re_sen_pre = self.drop(re_sen_pre)
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature

    # # space aug for imix
    # def forward(self, x1, **kwargs):  # dataset_train_imixspace_cross
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         # for i-mix
    #         # bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         # ori_sen_pre_imix = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #         # ori_sen_pre_imix = self.drop(ori_sen_pre_imix)
    #         # bert_output_imix = self.drop(bert_output_imix)
    #
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #         re_sen_pre_mix = self.drop(re_sen_pre)
    #
    #         ori_mean = self.generate_hidden_mean(ori_sen_pre_mix, kwargs['ori_label'])
    #         re_mean = self.generate_hidden_mean(re_sen_pre_mix, kwargs['re_label'])
    #
    #         new_re_sen_pre, new_ori_sen_pre = None, None
    #         for i in range(ori_sen_pre_mix.shape[0]):
    #             # gen_re_example = ori_sen_pre_mix[i] - ori_mean[kwargs['ori_label'][i].item()] + re_mean[
    #             #     kwargs['re_label'][i].item()]
    #             gen_ori_example = re_sen_pre_mix[i] - re_mean[kwargs['re_label'][i].item()] + ori_mean[kwargs['ori_label'][i].item()]
    #             # if new_re_sen_pre is None:
    #             #     new_re_sen_pre = gen_re_example.unsqueeze(0)
    #             # else:
    #             #     new_re_sen_pre = torch.cat([new_re_sen_pre, gen_re_example.unsqueeze(0)], 0)
    #
    #             if new_ori_sen_pre is None:
    #                 new_ori_sen_pre = gen_ori_example.unsqueeze(0)
    #             else:
    #                 new_ori_sen_pre = torch.cat([new_ori_sen_pre, gen_ori_example.unsqueeze(0)], 0)
    #
    #
    #
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         # re_sen_pre_mix, re_label_aux, re_lam = self.imix(re_sen_pre_mix, kwargs['mix_alpha'])
    #
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, new_ori_sen_pre], dim=0)
    #         # tem_re_pre = torch.cat([re_sen_pre_mix, new_re_sen_pre], dim=0)
    #
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #         # tem_re_pre = self.mix_fc1(tem_re_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         # tem_re_pre = nn.functional.normalize(tem_re_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         # re_bert_output_mix, re_bert_output_imix = tem_re_pre[:batch_size], tem_re_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         # re_mix_logits = re_bert_output_mix.mm(re_bert_output_imix.t())
    #         mix_logits /= self.temp
    #         # re_mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #         # re_mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #         # Obtain the representation vector for the classification learning branch
    #         # r_ids = kwargs['r_sen']['input_ids']
    #         # r_attention_mask = kwargs['r_sen']['attention_mask']
    #         # r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         # re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #         #
    #         # ori_mean = self.generate_hidden_mean(ori_sen_pre_mix, kwargs['ori_label'])
    #         # re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         # re_sen_pre = None
    #         # for i in range(ori_sen_pre_mix.shape[0]):
    #         #     gen_example = ori_sen_pre_mix[i] - ori_mean[kwargs['ori_label'][i].item()] + re_mean[
    #         #         kwargs['re_label'][i].item()]
    #         #     if re_sen_pre is None:
    #         #         re_sen_pre = gen_example.unsqueeze(0)
    #         #     else:
    #         #         re_sen_pre = torch.cat([re_sen_pre, gen_example.unsqueeze(0)], 0)
    #
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature

    # left imix & right space aug v2
    # def forward(self, x1, **kwargs): # train function dataset_train_limix_rspace_v2
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         # for i-mix
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_i = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_i)
    #
    #
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, ori_sen_pre_imix], dim=0)
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #
    #         ori_mean = self.generate_hidden_mean(ori_sen_pre_i, kwargs['ori_label'])
    #         re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #
    #         new_re_sen_pre = None
    #         for i in range(ori_sen_pre_i.shape[0]):
    #             # 此处的ori_sen_pre_mix找的有问题
    #             # 当权重为0.0001时 private 0.26231
    #             gen_example = 0.0001 * (ori_sen_pre_i[i] - ori_mean[kwargs['ori_label'][i].item()]) + re_mean[
    #                 kwargs['re_label'][i].item()]
    #             if new_re_sen_pre is None:
    #                 new_re_sen_pre = gen_example.unsqueeze(0)
    #             else:
    #                 new_re_sen_pre = torch.cat([new_re_sen_pre, gen_example.unsqueeze(0)], 0)
    #
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         # ori_sen_pre = torch.cat([ori_sen_pre, ori_sen_pre_i], dim=0)
    #         # re_sen_pre = torch.cat([re_sen_pre, new_re_sen_pre], dim=0)
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(new_re_sen_pre)
    #
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature

    # def forward(self, x1, **kwargs): # train function dataset_train_labeldes_limix_rspace_v2
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         ori_sen_pre_out = ori_sen_pre
    #         ori_sen_pre_mix = self.drop(ori_sen_pre)
    #         # for i-mix
    #         bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #         ori_sen_pre_i = self.get_sen_att(x1, bert_output_imix, 'ori', attention_mask)
    #         ori_sen_pre_imix = self.drop(ori_sen_pre_i)
    #         # bert_output_imix = self.drop(bert_output_imix)
    #
    #
    #         ori_sen_pre_mix, labels_aux, lam = self.imix(ori_sen_pre_mix, kwargs['mix_alpha'])
    #         tem_ori_pre = torch.cat([ori_sen_pre_mix, ori_sen_pre_imix], dim=0)
    #         tem_ori_pre = self.mix_fc(tem_ori_pre)
    #
    #         tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
    #         bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
    #         mix_logits = bert_output_mix.mm(bert_output_imix.t())
    #         mix_logits /= self.temp
    #         mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
    #
    #
    #         des_ids = kwargs['des_sen']['input_ids']
    #         # des_basz = des_ids.shape[0]
    #         des_attention_mask = kwargs['des_sen']['attention_mask']
    #         des_output = self.model(des_ids, attention_mask=des_attention_mask, output_hidden_states=True)
    #         des_imix1 = self.get_sen_att(kwargs['des_sen'], des_output, 'des', des_attention_mask)
    #
    #         # ori_des_imix1 = self.drop(des_imix1)
    #         # des_imix2 = self.drop(des_imix1)
    #         #
    #         # des_imix1, des_labels_aux, des_lam = self.imix(ori_des_imix1, kwargs['mix_alpha'])
    #         # tem_des_pre = torch.cat([des_imix1, des_imix2], dim=0)
    #         # tem_des_pre = self.des_fc(tem_des_pre)
    #         # tem_des_pre = nn.functional.normalize(tem_des_pre, dim=1)
    #         # des_output_mix, des_output_imix = tem_des_pre[:des_basz], tem_des_pre[des_basz:]
    #         # des_mix_logits = des_output_mix.mm(des_output_imix.t())
    #         # des_mix_logits /= self.temp
    #         # des_mix_labels = torch.arange(des_basz, dtype=torch.long).cuda()
    #
    #
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #
    #         # re_mean = self.generate_hidden_mean(re_sen_pre, kwargs['re_label'])
    #         # new_re_sen_pre = None
    #         # for i in range(ori_sen_pre_i.shape[0]):
    #         #     gen_example = 0.0001 * (ori_sen_pre_i[i] - des_imix1[kwargs['ori_label'][i].item(), :]) + re_mean[
    #         #         kwargs['re_label'][i].item()]
    #         #     if new_re_sen_pre is None:
    #         #         new_re_sen_pre = gen_example.unsqueeze(0)
    #         #     else:
    #         #         new_re_sen_pre = torch.cat([new_re_sen_pre, gen_example.unsqueeze(0)], 0)
    #
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         # ori_sen_pre = torch.cat([ori_sen_pre], dim=0)
    #         # re_sen_pre = torch.cat([re_sen_pre], dim=0)
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam, ori_sen_pre_out, des_imix1
    #                # des_mix_logits, des_mix_labels, des_labels_aux, des_lam
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature
    # Calculate the weight of each word
    def get_alpha(self, word_mat, data_type, mask):
        if data_type == 'ori':
            # representation learning  attention
            # att_w = self.ori_word_atten(word_mat)
            # att_w = self.ori_tanh(att_w)
            # att_w = self.ori_word_weight(att_w)
            att_w = self.ori_att(word_mat)
        # elif data_type == 'des':
        #     att_w = self.des_word_atten(word_mat)
        #     att_w = self.des_tanh(att_w)
        #     att_w = self.des_word_weight(att_w)
        else:
            att_w = self.re_att(word_mat)
            # classification learning  attention
            # att_w = self.re_word_atten(word_mat)
            # att_w = self.re_tanh(att_w)
            # att_w = self.re_word_weight(att_w)

        mask = mask.unsqueeze(2)
        att_w = att_w.masked_fill(mask == 0, float('-inf'))
        att_w = F.softmax(att_w, dim=1)
        return att_w

    # Get useful words vectors
    def get_word(self, sen, bert_output, mask):
        input_t2n = sen['input_ids'].cpu().numpy()
        sep_location = np.argwhere(input_t2n == 103)
        sep_location = sep_location[:, -1]

        # loc[0:size:2] 按步长取值

        select_index = list(range(sen['length'][0]))
        select_index.remove(0)  # 删除cls
        lhs = bert_output.last_hidden_state
        res = bert_output.hidden_states[8]
        relength = []
        recomposing = []
        mask_recomposing = []
        for i in range(lhs.shape[0]):
            select_index_f = select_index.copy()
            relength.append(sep_location[i] - 1)
            select_index_f.remove(sep_location[i])
            select_row = torch.index_select(lhs[i], 0,
                                            index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
            select_mask = torch.index_select(mask[i], 0,
                                             index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
            recomposing.append(select_row)
            mask_recomposing.append(select_mask)
        matrix = torch.stack(recomposing)
        mask = torch.stack(mask_recomposing)
        return matrix, mask

    # Get the representation vector after calculating the attention mechanism
    def get_sen_att(self, sen, bert_output, data_type, mask):
        word_mat, select_mask = self.get_word(sen, bert_output, mask)
        word_mat = self.drop(word_mat)
        att_w = self.get_alpha(word_mat, data_type, select_mask)
        word_mat = word_mat.permute(0, 2, 1)
        sen_pre = torch.bmm(word_mat, att_w).squeeze(2)
        return sen_pre

    def imix(self, input, alpha, share_lam=False):
        if not isinstance(alpha, (list, tuple)):
            alpha = [alpha, alpha]
        beta = torch.distributions.beta.Beta(*alpha)
        randind = torch.randperm(input.shape[0], device=input.device)
        if share_lam:
            lam = beta.sample().to(device=input.device)
            lam = torch.max(lam, 1. - lam)
            lam_expanded = lam
        else:
            lam = beta.sample([input.shape[0]]).to(device=input.device)
            lam = torch.max(lam, 1. - lam)
            lam_expanded = lam.view([-1] + [1] * (input.dim() - 1))
        output = lam_expanded * input + (1. - lam_expanded) * input[randind]
        return output, randind, lam


# # Calculate the weight of each word
#     def get_alpha(self, word_mat, data_type, mask):
#         if data_type == 'ori':
#             # representation learning  attention
#             att_w = self.ori_word_atten(word_mat)
#             att_w = self.ori_tanh(att_w)
#             att_w = self.ori_word_weight(att_w)
#         elif data_type == 'des':
#             att_w = self.des_word_atten(word_mat)
#             att_w = self.des_tanh(att_w)
#             att_w = self.des_word_weight(att_w)
#         else:
#             # classification learning  attention
#             att_w = self.re_word_atten(word_mat)
#             att_w = self.re_tanh(att_w)
#             att_w = self.re_word_weight(att_w)
#
#         mask = mask.unsqueeze(2)
#         att_w = att_w.masked_fill(mask == 0, float('-inf'))
#         att_w = F.softmax(att_w, dim=1)
#         return att_w
#
#     # Get useful words vectors
#     def get_word(self, sen, bert_output, mask):
#         input_t2n = sen['input_ids'].cpu().numpy()
#         sep_location = np.argwhere(input_t2n == 103)
#         sep_location = sep_location[:, -1]
#
#         # loc[0:size:2] 按步长取值
#
#         select_index = list(range(sen['length'][0]))
#         select_index.remove(0)  # 删除cls
#         lhs = bert_output.last_hidden_state
#         res = bert_output.hidden_states[8]
#         relength = []
#         recomposing = []
#         mask_recomposing = []
#         for i in range(lhs.shape[0]):
#             select_index_f = select_index.copy()
#             relength.append(sep_location[i] - 1)
#             select_index_f.remove(sep_location[i])
#             select_row = torch.index_select(lhs[i], 0,
#                                             index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
#             select_mask = torch.index_select(mask[i], 0,
#                                              index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
#             recomposing.append(select_row)
#             mask_recomposing.append(select_mask)
#         matrix = torch.stack(recomposing)
#         mask = torch.stack(mask_recomposing)
#         return matrix, mask
#
#     # Get the representation vector after calculating the attention mechanism
#     def get_sen_att(self, sen, bert_output, data_type, mask):
#         word_mat, select_mask = self.get_word(sen, bert_output, mask)
#         word_mat = self.drop(word_mat)
#         att_w = self.get_alpha(word_mat, data_type, select_mask)
#         word_mat = word_mat.permute(0, 2, 1)
#         sen_pre = torch.bmm(word_mat, att_w).squeeze(2)
#         return sen_pre
#     def imix(self, input, alpha, share_lam=False):
#         if not isinstance(alpha, (list, tuple)):
#             alpha = [alpha, alpha]
#         beta = torch.distributions.beta.Beta(*alpha)
#         randind = torch.randperm(input.shape[0], device=input.device)
#         if share_lam:
#             lam = beta.sample().to(device=input.device)
#             lam = torch.max(lam, 1. - lam)
#             lam_expanded = lam
#         else:
#             lam = beta.sample([input.shape[0]]).to(device=input.device)
#             lam = torch.max(lam, 1. - lam)
#             lam_expanded = lam.view([-1] + [1] * (input.dim() - 1))
#         output = lam_expanded * input + (1. - lam_expanded) * input[randind]
#         return output, randind, lam
